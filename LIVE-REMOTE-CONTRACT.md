# GitHub Pages remote catalog contract check

This read-only GitHub Action checks that the currently published **synthetic** catalog can be searched remotely using the same version-pointer, SHA-256 manifest, and content-addressed shard protocol used by the BookBridge v0.1.8 remote-only engine.

It verifies both title and author indexes, decompresses only the two required synthetic shards, and checks that their marker metadata agrees. It runs weekly, on manual dispatch, and on relevant PRs. A failed check indicates that the hosted data protocol or availability requires investigation.

This job does **not** upload, publish, or approve any catalog. It does not install the LibGen engine, run the Windows Studio, access user seedboxes, download SQLite, or authorize acquisitions.

The current publicly hosted catalog contains **synthetic test records only**. The privately staged legacy LibGen-derived metadata must not be published to this repository or GitHub Pages without separate provenance and publication authorization review.
