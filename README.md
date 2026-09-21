# docstracker-framework

The Extractor → Differ → Analyzer → Synthesizer → Notifier pipeline behind
[docstracker](https://github.com/inimeve/docstracker), extracted into its own
repository per [ADR-0009](https://github.com/inimeve/docstracker/blob/master/docs/adr/0009-engine-repo-split-ambito-repo.md).

An **Ámbito Repo** (docstracker is the first one) depends on this repo as a
version-pinned git dependency and supplies only a `config.yaml` plus that
ámbito's Page/Navigation Snapshots and Analyses. This repo carries no
Watch Target data of its own.

## Install

```
pip install git+https://github.com/inimeve/docstracker-framework.git@v0.1.0
```

## Develop

```
pip install -e .
pip install -r requirements.txt
pytest
```

Tests run against a fake `Extractor`; nothing here calls a real
documentation source over the network. `Crawler` (the BFS-prefix HTML
`Extractor` implementation) and `nav_fetcher` are exercised against a local
`pytest-httpserver` fixture, not any live site.
