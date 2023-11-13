# Terraform Cloud Self-Service Workflows
Automation tooling for Terraform Cloud (TFC) or Terraform Enterprise (TFE) self-service workflows, including interacting with Version Control Systems (VCS).

## Requirements
- Python 3.x installed
- Python package `pytfc` >= 0.0.23 installed
- Python package `python-gitlab` >= 3.15.0 installed
- TFC/TFE API token
- VCS API token

## Setup
- Fork this repo (or copy the contents into your own dedicated repo)
- Update the contents of `templates/main.tf` with the Terraform code you want to deploy.
- Update the contents of `templates/template.tfvars.tpl` with the applicable Terraform variable keys for your deployments.

See the example [templates](./templates/) directory for reference.

## Usage
The [scripts](./scripts/) directory contains scripts that can be run interactively or inserted into a pipeline to enable self-service workflows with TFC/TFE and a VCS.

### Create TFC Workspace and GitLab config
[create_tfc_ws_gl.py](./scripts/create_tfc_ws_gl.py)

Set up the required environment variables:
```sh
# Terraform Cloud
export TFE_TOKEN=
export TFE_ORG=

# GitLab
export GL_TOKEN=
export GL_PROJECT_ID=
```

Execute the script:
```sh
create_tfc_ws_gl.py --name my-new-ws \
                    --project-name my-tfc-project \
                    --vcs-repo alexbasista/tfc-ss-framework \
                    --oauth-token-id ot-abcdefg123456789 \
                    --varset-name my-aws-creds \
                    --templates-dir ../templates \
                    --var pet_length 2 \
                    --var pet_prefix test \
                    --var pet_separator _ \
                    --outputs test0 test1
```
> In this example, my Terraform configuration calls for (3) input variables. The values for each of them are specified using the `--var` argument (optional). The `--outputs` argument is also optional, and will return any output values from the output key(s) that are specified.
