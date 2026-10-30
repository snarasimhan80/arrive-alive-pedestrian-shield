# Handover checklist

## What the next developer gets

- Repository: https://github.com/snarasimhan80/arrive-alive-pedestrian-shield
- Public demo: https://134.209.149.217/footpath-demo/
- `README.md`: clone, install, run and deploy commands.
- `docs/DEVELOPMENT.md`: file map, change workflow and acceptance tests.
- `docs/DEPLOYMENT.md`: real server paths, access, release, rollback and logs.
- Local models, four generated obstruction clips and a filmed clear control.
- Source/model/media licenses and provenance.

## Owner actions for access

Anyone can clone the public repository. To allow direct pushes, invite the
developer's GitHub username as a collaborator in repository Settings →
Collaborators. Alternatively they can fork and submit PRs without write
access. Review changes before merging to `main`.

For updates to Krsaangi, hand over the dedicated demo deployment key
privately, or ask the owner to authorize the developer's own public key on
the restricted `footpath-deployer` account. No administrator account or
owner's SSH key needs to be shared. The private deployment credential is
not part of GitHub or `/source.zip`. See `RESTRICTED_ACCESS.md` for the
boundary and owner-only rotation/revocation instructions.

For hosting on a different server, no Krsaangi credential is needed: use
the code, included models and Docker/native setup with that server's own
credentials. Grant GitHub write access and Krsaangi access separately.

## First session

1. Clone the repo and follow native local setup.
2. Start the app and analyze one saved clip through the browser.
3. Run all five local clip checks and inspect the marked output.
4. Make a small branch change and review it through a PR.
5. After merge, pull `main`, run deployment dry-run, deploy and verify the
   public result. Save the printed backup ID.
6. Learn the rollback/status commands before making larger changes.

## Boundaries to preserve

- The four Indian street examples are generated, not actual CCTV incidents.
- Red tracks are observed image-space movement, not proof of its cause.
- Tiny people and occlusions can defeat the tracker; review the evidence.
- The simple score is not FR-24 exposure or an accident probability.
- Real metre/km/h estimates require surveyed camera/site inputs.
- Preserve the original illustrative site table and separate uploaded rows.
- Keep the app's AGPL source available when updating the public service.
- Keep uploads, credentials, keys, environments and large generator weights
  out of Git and release ZIPs.
