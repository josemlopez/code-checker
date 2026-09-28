# Security and local data

Code Checker is a local development tool. Run its HTTP server on loopback
(`127.0.0.1`), not on a public network interface. It is not a multi-user service.

## Credentials

SSH, GitHub CLI and Codex CLI use the credentials already configured on the
machine running them. This repository supplies no account, token, SSH key or
access to any server. Configure your own tools separately; never commit their
configuration directories or credentials here.

## Analysis data

`.codechecker/` holds private runtime state, project indexes and model results.
Local indexes may contain source code and documentation. SSH indexes omit source
bodies, but paths, metadata and model responses may still be sensitive. Exported
reports must also be treated as private project data. If `CODE_CHECKER_DATA`
points elsewhere, protect that directory too.

Reference media, local verification reports, logs, environment files, database
files and common credential formats are excluded by `.gitignore`. An ignore file
does not inspect file contents and cannot protect files added with `git add -f`.
Review the exact staged files and run a secret scanner before publishing changes.

## Remote access and models

Remote analysis reads through SSH without installing files or running inspected
project code. Git comparisons do not fetch, check out, or change branches. The
SSH account retains its existing permissions; this behavior is not an operating
system access-control boundary. A dedicated read-only account can provide one.

Static metrics need no language model. When model evaluation (including lazy
evaluation) is enabled, selected source and documentation are passed to the
configured provider. Automatic lazy evaluation is enabled by default in the UI;
disable it before connecting a project if it must not be sent to a provider.
Inspect the context and provider settings before evaluating sensitive projects.

## Reporting a vulnerability

Do not put secrets, private project dumps or credentials in public issues.
Use GitHub private vulnerability reporting when enabled for this repository.
