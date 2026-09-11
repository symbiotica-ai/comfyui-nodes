# Roadmap

Ideas queued for the pack. One block per idea, numbered by its GitHub issue —
refer to an entry as #N. Move a block to the CHANGELOG when it ships.

## [#71](https://github.com/symbiotica-ai/comfyui-nodes/issues/71) — Approved assets go back into the dataset

An approved render should land back in the project's `dataset/` under its
category and asset name, so it can be picked as the base for a future
generation — this month's approved crate becomes next month's reference.

- Today the approve lane stops at the save path; `dataset/<Category>/` is
  seeded by hand and never learns what was accepted.
- Once it does, `Dataset Reference` and `Pick Similar Asset From Project` offer
  approved work like any seeded reference, and the style loop is closed.
- Open: copy or reference in place; write from the Pick node at approve time or
  from its own node in the lane; what a re-approval does to the earlier version.

## [#66](https://github.com/symbiotica-ai/comfyui-nodes/issues/66) — Render lane: use / don't use reference image

Generate with or without a client reference. The architect chat's `image`
comes from the Pick Client Reference node; an asset with no client refs (or a
deliberately empty pick) should still compose and render — a use/don't-use
switch, or an empty pick simply meaning "no reference".

![pick client reference](assets/roadmap/pick-client-reference-required.png)

## [#67](https://github.com/symbiotica-ai/comfyui-nodes/issues/67) — Preload models at workflow start

Load the diffusion model, VAE, controlnets, CLIP and loras at workflow start
instead of at first queue — the GPU is paid for whether it renders or not, so
warm it while the user is still picking assets and writing prompts. First
generation should not carry the cold-load penalty.

## Recipes and Asset Focus — open threads (no issue filed yet)

Left open on 2026-09-11 after the recipes build; one line each, the decision
still open. Move to an issue when one is picked up.

- The `auto` toggle on the Recipes node (save on edit, load/create on a name
  change) has unit tests only; nobody has watched it on a canvas.
- `CHANGELOG.md` stops at 2026.9.21; everything since shipped by `push.sh`
  (live name resolver, auto toggle, project resolved from the open workflow,
  two-word buttons, Asset Focus categories split by canvas tiles with
  `category_recipe`/`width`/`height`). The next release needs one entry for it.
- A `recipe:<key>?` toggle writes active or bypassed only; muted (mode 2) is
  not offered.
- The bakery template still carries a `recipe:plot` String and a Join String
  Multi to build the recipe name; Asset Focus's `category_recipe` output makes
  both redundant.
- The ten older bakery categories are not captured as recipes yet, and the
  engine pins on the studio-assets Volume are the old 80-node exports — every
  generated workflow needs re-export, one bindings file, re-pin.
- `push.sh` removed `py/audio_duration.py` and `py/prompt_speech_split.py`
  from the Volume (on it, in no release); confirm no workflow used their nodes.
- The Control Image preview (`web/js/control_image.js`) draws through
  `node.imgs`; only its URL builder is unit-tested.
- Hub side: the module library dir `user/default/symbiotica-modules` is not
  symlinked to the shared Volume (`canvas_entry.user_tree`), so published
  modules stay per user.
