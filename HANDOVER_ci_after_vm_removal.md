# Handover: CI clean-up once the VM version of Web-LaTeX is removed

Written 2026-10-21, after the pod migration was merged into `dev` (PR #1). Facts marked *(verified)* were read
from this repo on that date; facts marked *(inferred)* must be checked before relying on them.

## Situation

Web-LaTeX now exists in two runtimes side by side:

- **Pod runtime, v2.x** (`appstore.yaml`, `image/`, `.github/workflows/image.yml`): the AppStore reads
  `appstore.yaml`, runs the image from GHCR as a pod. No Terraform, no Packer.
- **VM runtime, v1.x** (`terraform/`, `packer/`, `.github/workflows/terraform.yml`, `.github/workflows/packer.yml`,
  `.github/actions/action.yml`): left from the previous semester's team. Nobody owns it, and it is meant to be removed.

The VM side is still in the repo only so that v1.x versions keep working. The pod work does not use it.

## Why a check is red today *(verified)*

`terraform.yml` and `packer.yml` run on **every push** (`on: push:`) and on pull requests to `main`. The
`Terraform` job runs `terraform fmt -check` and fails because `terraform/main.tf` is not formatted (7 lines of
whitespace/indentation in the `team_vm_refreshed` data source and the `team_ip` local, left by earlier IPv6 edits).
It is not caused by the pod work. The `Packer` job passes. The `Build image (pod runtime)` job passes.

A quick fix, if the red check matters before the removal: run `terraform fmt terraform/main.tf`, commit only that
file (`style: terraform fmt`), and open a PR into `dev`. It changes no behaviour (`git diff -w` is empty).

## TODO when the VM version is removed

Do this in one PR into `dev`, after the team has decided to drop v1.x.

1. **Check that v1.x deployments are not needed any more.** *(inferred)* The platform deploys an app version from a
   commit of this repo, so existing v1.x versions keep working as long as their commits/tags still exist. Do not
   rewrite or delete history/tags that old versions point to. Ask the platform owner before removing files.
2. **Delete the VM files:** `terraform/`, `packer/`, `.github/workflows/terraform.yml`,
   `.github/workflows/packer.yml`, `.github/actions/action.yml` (the local "setup-packer" action, used only by
   `packer.yml`).
3. **Delete secrets/environments that only the VM workflows used:** the `TF_API_TOKEN` secret and the `production`
   environment (both are referenced only by `terraform.yml` and `packer.yml`). *(verified: referenced there;
   check the repo settings for anything else)*
4. **Delete the stale branch** `fix/packer-ssh-ipv6` (one commit, only `packer/` files) once step 2 is merged.
5. **README:** remove the VM sections (Deployment-Dauer, Konfigurierbare Variablen for terraform, VM-Deployment)
   and keep the "Pod-Variante" section as the main text. The `assignment_files` / VM wording is obsolete then.
6. **`image.yml`:**
   - remove `feat/pod-runtime` from the trigger list once that branch is gone (`main`, `dev` stay);
   - optional: build without pushing on pull requests, so a broken Dockerfile is caught before merge (today the
     image is only built after a push to `main`, `dev` or `feat/pod-runtime`);
   - optional: add a `pull_request` check for `appstore.yaml` (see `parse_spec()` in the `deployment` repo,
     `k8s/src/appstore-api/shared/appstore_shared/k8s/spec.py` on `spike/dev`).
7. **Do not remove** `image/`, `appstore.yaml`, `.gitattributes`. The Flask app and templates that used to be
   heredocs in `packer/scripts/provision.sh` now live in `image/app/`, the demo project in `image/demo/`. Removing
   `packer/` does not delete the app.

## Notes for whoever does it

- Other app repos have the same two workflows (2026-10-21: the latest Terraform runs of `pgAdmin`, `template-app` and
  `Online-IDE` on their `feat/pod-runtime` branches succeeded; I did not check the other failures in detail). The
  same clean-up applies to them whenever their VM versions go.
- The Terraform job also runs TFLint and tfsec; if the VM files are kept longer, those can fail later when the
  tools update (`tflint_version: latest`, `hashicorp/setup-terraform@v1` is old and prints `set-output`
  deprecation warnings).
- `Windows-Desktop-App` stays a VM (epic decision), so its Terraform/Packer CI is a separate question.
