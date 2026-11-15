# Owner: A (Infra & Platform). Everything for Phase 2 lives in the single folder infra/.
# Only role A runs tf-apply / ami / destroy-*; everyone else may run tf-plan and the checks.

TF       := terraform -chdir=infra
GH_OWNER ?= $(shell git remote get-url origin 2>/dev/null | sed -E 's#.*github\.com[:/]([^/]+)/.*#\1#' | tr '[:upper:]' '[:lower:]')
# Newest commit that changed the image (same paths as .github/workflows/docker.yml).
# If that commit was not the head of its push, GHCR has no tag for it: pass IMAGE_TAG=<sha7>.
IMAGE_TAG ?= $(shell git log -1 --format=%H -- app web scripts/calibrate.py .github/workflows/docker.yml 2>/dev/null | cut -c1-7)
IMAGE    ?= ghcr.io/$(GH_OWNER)/streamlite:$(IMAGE_TAG)
MODE     ?= baked
LOADGEN  ?= false
TF_VARS   = -var 'image=$(IMAGE)' -var 'user_data_mode=$(MODE)' -var 'enable_loadgen=$(LOADGEN)'
LOAD_ENV  = set -a && source .env.tf && set +a
AWS_DEFAULT_REGION ?= ap-south-1
export AWS_DEFAULT_REGION

.PHONY: tf-init tf-validate tf-test tf-plan tf-apply ami image-check env publish-site smoke lab-up destroy-lab \
        loadgen-shell infra-lint destroy-all

tf-init: ## terraform init with the shared S3 state (needs infra/.backend.hcl)
	@test -f infra/.backend.hcl || { echo "copy infra/backend.hcl.example to infra/.backend.hcl first"; exit 1; }
	$(TF) init -backend-config=.backend.hcl

tf-validate: ## terraform fmt check + validate without AWS credentials or state
	$(TF) fmt -check -diff
	$(TF) init -backend=false -input=false >/dev/null
	$(TF) validate

tf-test: ## offline terraform tests against mock providers (no AWS account needed)
	$(TF) init -backend=false -input=false >/dev/null
	$(TF) test

tf-plan: ## terraform plan (MODE=baked|naive LOADGEN=true|false IMAGE_TAG=<sha7>)
	$(TF) plan $(TF_VARS)

tf-apply: ## terraform apply (role A only; same variables as tf-plan)
	$(TF) apply $(TF_VARS)

image-check: ## confirm the GHCR image tag exists and is pullable without login
	@echo "image: $(IMAGE)"
	@docker manifest inspect $(IMAGE) >/dev/null 2>&1 || { \
	  echo "not found or not public: check the GHCR package page, then pass IMAGE_TAG=<sha7>"; exit 1; }
	@echo "ok: image is public"

ami: image-check ## bake the AMI with Packer and write infra/ami.auto.tfvars
	packer init infra/streamlite.pkr.hcl
	packer build -var 'image=$(IMAGE)' -var 'tag=$(IMAGE_TAG)' infra/streamlite.pkr.hcl
	@ami=$$(jq -r '.builds[-1].artifact_id | split(":")[1]' infra/manifest.json); \
	  echo "ami_id = \"$$ami\"" > infra/ami.auto.tfvars; echo "wrote infra/ami.auto.tfvars: $$ami"

env: ## write terraform outputs to .env.tf for scripts
	@$(TF) output -json | jq -r 'to_entries[] | "\(.key | ascii_upcase)=\(.value.value)"' > .env.tf
	@echo "wrote .env.tf:"; sed 's/^/  /' .env.tf

publish-site: ## upload web/ to the site bucket and invalidate CloudFront
	@$(LOAD_ENV) && \
	  aws s3 sync web/ "s3://$$SITE_BUCKET" --delete --region "$$REGION" && \
	  aws cloudfront create-invalidation --distribution-id "$$CLOUDFRONT_ID" --paths '/*' \
	    --query 'Invalidation.Id' --output text

smoke: ## Phase 2 acceptance checks (SPREAD=1 adds the 3-instance spread check)
	@SPREAD=$(SPREAD) bash infra/smoke.sh

lab-up: ## start a lab session: apply with the loadgen instance
	$(MAKE) tf-apply LOADGEN=true
	$(MAKE) env

destroy-lab: ## end a lab session: reset the ASG, remove the loadgen, show what still runs
	bash infra/reset_asg.sh
	$(MAKE) tf-apply LOADGEN=false
	$(MAKE) env
	@$(LOAD_ENV) && echo "running project instances:" && \
	  aws ec2 describe-instances --region "$$REGION" \
	    --filters Name=tag:project,Values=hotstar-scale-lab Name=instance-state-name,Values=pending,running \
	    --query 'Reservations[].Instances[].[InstanceId,InstanceType,Tags[?Key==`Name`]|[0].Value]' --output table

loadgen-shell: ## open an SSM shell on the loadgen
	@$(LOAD_ENV) && test -n "$$LOADGEN_INSTANCE_ID" || { echo "no loadgen: run make lab-up"; exit 1; }
	@$(LOAD_ENV) && aws ssm start-session --region "$$REGION" --target "$$LOADGEN_INSTANCE_ID"

infra-lint: ## terraform fmt, packer fmt/validate and shellcheck for infra/
	$(TF) fmt -check -diff
	packer fmt -check infra/streamlite.pkr.hcl
	packer init infra/streamlite.pkr.hcl >/dev/null
	packer validate -syntax-only infra/streamlite.pkr.hcl
	shellcheck infra/*.sh

destroy-all: ## AFTER THE VIVA ONLY: destroy everything, deregister AMIs, delete snapshots
	@read -r -p "Destroy the whole stack and all hsl AMIs? Type 'destroy': " a && [ "$$a" = destroy ]
	$(TF) apply $(TF_VARS) -var force_destroy_results=true -target=aws_s3_bucket.results -auto-approve
	$(TF) destroy $(TF_VARS) -var force_destroy_results=true
	@for ami in $$(aws ec2 describe-images --owners self --filters Name=tag:project,Values=hotstar-scale-lab \
	    --query 'Images[].ImageId' --output text); do \
	  snaps=$$(aws ec2 describe-images --image-ids $$ami --query 'Images[].BlockDeviceMappings[].Ebs.SnapshotId' --output text); \
	  aws ec2 deregister-image --image-id $$ami && echo "deregistered $$ami"; \
	  for s in $$snaps; do aws ec2 delete-snapshot --snapshot-id $$s && echo "  deleted $$s"; done; \
	done
