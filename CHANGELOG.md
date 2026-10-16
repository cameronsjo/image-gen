# Changelog

## [0.2.0](https://github.com/cameronsjo/image-gen/compare/v0.1.8...v0.2.0) (2026-10-16)


### ⚠ BREAKING CHANGES

* **mcp:** /mcp now rejects untrusted Host/Origin headers with HTTP 403. Before upgrading LAN/Traefik deployments, configure MCP_ALLOWED_HOSTS and matching MCP_ALLOWED_ORIGINS as JSON arrays, for example ["images.example.lan"] and ["https://images.example.lan"]. These variable names are unprefixed and do not accept comma-separated strings.

### Features

* **mcp:** document protected-host upgrade requirements ([311273b](https://github.com/cameronsjo/image-gen/commit/311273bc7fd82e6fa36b677b8dc05eadbe3039b0))
* **mcp:** support per-generation model selection ([2efeffa](https://github.com/cameronsjo/image-gen/commit/2efeffa1ecc173df4b08b7ef74bf62417567123d))
* **mcp:** support per-generation model selection ([7b0ec7f](https://github.com/cameronsjo/image-gen/commit/7b0ec7f6114a1541e6d7dd3405e0fe4b6f3fdccd))
* **providers:** add supported output-cost estimates ([0a3926a](https://github.com/cameronsjo/image-gen/commit/0a3926a3a34e83e1505d9a15e10cde5eb6f307fd))
* **providers:** add supported output-cost estimates ([40fef8c](https://github.com/cameronsjo/image-gen/commit/40fef8ce20734f94cbba16e31cc713cd6d3d9b63))
* **providers:** persist OpenRouter usage metadata ([e872b8d](https://github.com/cameronsjo/image-gen/commit/e872b8df497a033800848fd63812026cc3d4215e))
* **providers:** persist OpenRouter usage metadata ([802f87c](https://github.com/cameronsjo/image-gen/commit/802f87ce14ebbc6a430214fe8ddc7427bfece47b))
* **storage:** save descriptive contained image filenames ([615b109](https://github.com/cameronsjo/image-gen/commit/615b109d438eb69335a4ea1ba7b3ed0a452bbba3))
* **storage:** save descriptive contained image filenames ([3c374ac](https://github.com/cameronsjo/image-gen/commit/3c374ac414e0977d06a1ac86c224cce840761423))
* **ui:** show costs and totals for loaded history ([447713d](https://github.com/cameronsjo/image-gen/commit/447713d9afe4e0e4083f888a667117eed75f1316))
* **ui:** show history costs with server aggregates ([c45212c](https://github.com/cameronsjo/image-gen/commit/c45212c8736088ea3904e0490f543abc18909921))


### Bug Fixes

* **comfyui:** bound streamed image response size ([af459ee](https://github.com/cameronsjo/image-gen/commit/af459eee27f332a8fcef6a2758b713c1389d1b4a))
* **comfyui:** bound streamed image response size ([46febd0](https://github.com/cameronsjo/image-gen/commit/46febd04ddf7c6162c94b5978ad4f1fc8dc72d6d))
* **comfyui:** restore bounded image rejection logs ([a05e9a5](https://github.com/cameronsjo/image-gen/commit/a05e9a5e9c87fd05ac19bb4fbfce8438f9cb69aa))
* **estimates:** verify rendered values and log output estimates ([cd42a82](https://github.com/cameronsjo/image-gen/commit/cd42a820f63def92728975cb8e78d1feec5302f0))
* **mcp:** enforce identity expiry and request-origin protection ([eb11b03](https://github.com/cameronsjo/image-gen/commit/eb11b03b8be073c16f17c1c4e9ac79ce3e298441))
* **mcp:** reject authenticated tokens without a nonblank subject ([9ba9981](https://github.com/cameronsjo/image-gen/commit/9ba9981b688dab43a7a40900c75a8f9d371c69f7))
* **setup:** clean interrupted downloads and set model modes ([58b23cb](https://github.com/cameronsjo/image-gen/commit/58b23cb3a6523af1d8faec3f16d28e0419fba7d1))
* **setup:** verify pinned model download checksums ([b392203](https://github.com/cameronsjo/image-gen/commit/b392203b44f5869a8e6d62fca7be950550512b11))
* **setup:** verify pinned model download checksums ([9e8c9ae](https://github.com/cameronsjo/image-gen/commit/9e8c9aedba1cbea673b8c7ff8f27a220c4725dcd))
* **ui:** aggregate history costs beyond loaded rows ([3bb8a35](https://github.com/cameronsjo/image-gen/commit/3bb8a3542c95adddd14799bfa89edf722a0ee397))


### Documentation

* **api:** list the authenticated cost aggregate endpoint ([cf5816c](https://github.com/cameronsjo/image-gen/commit/cf5816c0e5a88d89b8c87c59179e841dbeb34b91))
* **mcp:** reconcile changelog ownership and ADR history ([f34b4b9](https://github.com/cameronsjo/image-gen/commit/f34b4b92796393518b13ec0d7c4b5c19180ea466))
* **mcp:** record approved SDK upgrade delivery ([f54793c](https://github.com/cameronsjo/image-gen/commit/f54793cb10a230075020f11c5f9c03d5cba45d8f))
* **mcp:** record round-three security verification ([e3bfeaa](https://github.com/cameronsjo/image-gen/commit/e3bfeaa8c298af01cf40885e0a0153ef368d3c2a))
* **tests:** describe sizing regression assertions ([237790d](https://github.com/cameronsjo/image-gen/commit/237790d08415856af53c209c6aca86b47fb354fc))

## [0.1.8](https://github.com/cameronsjo/image-gen/compare/v0.1.7...v0.1.8) (2026-10-05)


### Features

* **providers:** add local ComfyUI provider (FLUX.1-schnell) ([#20](https://github.com/cameronsjo/image-gen/issues/20)) ([620da29](https://github.com/cameronsjo/image-gen/commit/620da29c9e0db6faba1506883a2f76af36dac67f))
* web UI with dynamic model selection ([#18](https://github.com/cameronsjo/image-gen/issues/18)) ([b6caab4](https://github.com/cameronsjo/image-gen/commit/b6caab4d1f74e572854197546577212011e2e9de))

## [0.1.7](https://github.com/cameronsjo/image-gen/compare/v0.1.6...v0.1.7) (2026-06-28)


### Bug Fixes

* address multi-provider review follow-ups ([#9](https://github.com/cameronsjo/image-gen/issues/9), [#10](https://github.com/cameronsjo/image-gen/issues/10), [#11](https://github.com/cameronsjo/image-gen/issues/11), [#12](https://github.com/cameronsjo/image-gen/issues/12)) ([#16](https://github.com/cameronsjo/image-gen/issues/16)) ([a55dc61](https://github.com/cameronsjo/image-gen/commit/a55dc6186041732c586f9a649863eeb623a6305f))

## [0.1.6](https://github.com/cameronsjo/image-gen/compare/v0.1.5...v0.1.6) (2026-06-28)


### Features

* add shared exception hierarchy (foundation for multi-provider work) ([de5d8df](https://github.com/cameronsjo/image-gen/commit/de5d8df29dfed05aa4eec80af477d514d6b1aee9))
* multi-provider image generation + security hardening + standards ([#13](https://github.com/cameronsjo/image-gen/issues/13)) ([9d5ecbf](https://github.com/cameronsjo/image-gen/commit/9d5ecbf47cfdeebdbd284e61ec536caf378c6169))

## [0.1.5](https://github.com/cameronsjo/image-gen/compare/v0.1.4...v0.1.5) (2026-03-23)


### Documentation

* add field report for FastMCP ASGI integration fix ([f49258e](https://github.com/cameronsjo/image-gen/commit/f49258ec3ff8ae06507e06730a72c9008c824d82))

## [0.1.4](https://github.com/cameronsjo/image-gen/compare/v0.1.3...v0.1.4) (2026-03-23)


### Features

* add test suite, fix MCP path, update README ([219da89](https://github.com/cameronsjo/image-gen/commit/219da89a8379339f7abc36ac03668870848e25f0))


### Bug Fixes

* **mcp:** resolve 307 redirect and lifespan initialization on /mcp ([545689d](https://github.com/cameronsjo/image-gen/commit/545689d6337ae7b629a20f2d6db6d984c4ac7d70))


### Documentation

* add field report for first deploy pipeline ([e083bf6](https://github.com/cameronsjo/image-gen/commit/e083bf6203f1cdaa96ab540c5cf6a36fabf98d94))

## [0.1.3](https://github.com/cameronsjo/image-gen/compare/v0.1.2...v0.1.3) (2026-02-22)


### Bug Fixes

* copy source tree to runtime stage for editable install ([cb1ff0a](https://github.com/cameronsjo/image-gen/commit/cb1ff0ad4a05c54cf6b1d5346971323c8768f1dd))

## [0.1.2](https://github.com/cameronsjo/image-gen/compare/v0.1.1...v0.1.2) (2026-02-22)


### Bug Fixes

* include README.md in Docker build for hatchling ([4bc677e](https://github.com/cameronsjo/image-gen/commit/4bc677e94bc76c830ca39bf9cce3d75bff15fc1d))

## [0.1.1](https://github.com/cameronsjo/image-gen/compare/v0.1.0...v0.1.1) (2026-02-22)


### Features

* add Dockerfile and docker-publish workflow ([72d2265](https://github.com/cameronsjo/image-gen/commit/72d2265f37d77e04ec332f0f02fada1d0c78f3d3))
* implement image-gen service (Phase 1 + 2) ([a79c78b](https://github.com/cameronsjo/image-gen/commit/a79c78b6172e491cfbe2b6e628122e4da97eddf2))
* initial project scaffold ([184e59b](https://github.com/cameronsjo/image-gen/commit/184e59b0b862f4a59733b5b8c5c19d8ee40a3e9e))

## Changelog
