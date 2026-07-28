// ABOUTME: Frontend extension for Symbiotica Seed node.
// ABOUTME: Adds Randomize/Fixed Random/Last Queued buttons and intercepts API queue for range-aware seed generation.

import { app } from "../../../scripts/app.js";
import { registerSymbioticaExtension } from "./register.js";

const SPECIAL_SEED_RANDOM = -1;
const SPECIAL_SEED_INCREMENT = -2;
const SPECIAL_SEED_DECREMENT = -3;
const SPECIAL_SEEDS = [SPECIAL_SEED_RANDOM, SPECIAL_SEED_INCREMENT, SPECIAL_SEED_DECREMENT];

registerSymbioticaExtension(app, {
  name: "symbiotica.seed",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "SymbioticaSeed") return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);

      const node = this;
      node.lastSeed = null;
      node.lastSeedButton = null;

      const seedWidget = node.widgets?.find((w) => w.name === "seed");
      if (!seedWidget) return;

      // Hide the default "control_after_generate" widget — we replace it with buttons
      const controlWidget = node.widgets?.find(
        (w) => w.name === "control_after_generate",
      );
      if (controlWidget) {
        controlWidget.type = "converted-widget";
        controlWidget.computeSize = () => [0, -4];
        controlWidget.serializeValue = () => controlWidget.value;
      }

      function getRange() {
        const minW = node.widgets?.find((w) => w.name === "min_value");
        const maxW = node.widgets?.find((w) => w.name === "max_value");
        const lo = Math.min(
          Number(minW?.value ?? 0),
          Number(maxW?.value ?? 100),
        );
        const hi = Math.max(
          Number(minW?.value ?? 0),
          Number(maxW?.value ?? 100),
        );
        return { lo, hi };
      }

      function generateRandomSeed() {
        const { lo, hi } = getRange();
        let seed = Math.floor(Math.random() * (hi - lo + 1)) + lo;
        if (SPECIAL_SEEDS.includes(seed)) {
          seed = lo >= 0 ? 0 : lo;
        }
        return seed;
      }

      // --- Randomize Each Time button ---
      const randomizeBtn = node.addWidget(
        "button",
        "Randomize Each Time",
        null,
        () => {
          seedWidget.value = SPECIAL_SEED_RANDOM;
          node.graph?.setDirtyCanvas(true);
        },
      );
      randomizeBtn.serializeValue = () => undefined;

      // --- New Fixed Random button ---
      const fixedRandomBtn = node.addWidget(
        "button",
        "New Fixed Random",
        null,
        () => {
          seedWidget.value = generateRandomSeed();
          node.lastSeed = seedWidget.value;
          if (node.lastSeedButton) {
            node.lastSeedButton.name = `Last Seed: ${node.lastSeed}`;
          }
          node.graph?.setDirtyCanvas(true);
        },
      );
      fixedRandomBtn.serializeValue = () => undefined;

      // --- Use Last Queued Seed button ---
      node.lastSeedButton = node.addWidget(
        "button",
        "(Use Last Queued Seed)",
        null,
        () => {
          if (node.lastSeed != null) {
            seedWidget.value = node.lastSeed;
            node.graph?.setDirtyCanvas(true);
          }
        },
      );
      node.lastSeedButton.serializeValue = () => undefined;

      // --- API queue interception ---
      const origOnSerialize = node.onSerialize;
      node.onSerialize = function (o) {
        origOnSerialize?.apply(this, arguments);
      };

      // Intercept before queuing to resolve special seeds
      const origGetExtraMenuOptions = node.getExtraMenuOptions;
      node.getExtraMenuOptions = function (_, options) {
        origGetExtraMenuOptions?.apply(this, arguments);
      };
    };

    // Intercept prompt serialization to resolve sentinel seeds
    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (output) {
      onExecuted?.apply(this, arguments);
    };
  },

  async setup() {
    const origQueuePrompt = app.queuePrompt;
    app.queuePrompt = async function () {
      // Find all SymbioticaSeed nodes and resolve special seeds before sending
      const graph = app.graph;
      if (graph) {
        for (const node of graph._nodes || []) {
          if (node.comfyClass !== "SymbioticaSeed") continue;

          const seedWidget = node.widgets?.find((w) => w.name === "seed");
          if (!seedWidget) continue;

          const seedVal = Number(seedWidget.value);
          if (!SPECIAL_SEEDS.includes(seedVal)) {
            node.lastSeed = seedVal;
            continue;
          }

          const minW = node.widgets?.find((w) => w.name === "min_value");
          const maxW = node.widgets?.find((w) => w.name === "max_value");
          const lo = Math.min(
            Number(minW?.value ?? 0),
            Number(maxW?.value ?? 100),
          );
          const hi = Math.max(
            Number(minW?.value ?? 0),
            Number(maxW?.value ?? 100),
          );

          let newSeed;
          if (seedVal === SPECIAL_SEED_RANDOM) {
            newSeed = Math.floor(Math.random() * (hi - lo + 1)) + lo;
          } else if (seedVal === SPECIAL_SEED_INCREMENT) {
            newSeed =
              node.lastSeed != null ? node.lastSeed + 1 : lo;
            if (newSeed > hi) newSeed = lo;
          } else if (seedVal === SPECIAL_SEED_DECREMENT) {
            newSeed =
              node.lastSeed != null ? node.lastSeed - 1 : hi;
            if (newSeed < lo) newSeed = hi;
          }

          if (SPECIAL_SEEDS.includes(newSeed)) {
            newSeed = lo >= 0 ? 0 : lo;
          }

          node.lastSeed = newSeed;
          if (node.lastSeedButton) {
            node.lastSeedButton.name = `Last Seed: ${newSeed}`;
          }

          // Temporarily set the widget value for this queue call,
          // then restore the sentinel so the button state persists
          const originalValue = seedWidget.value;
          seedWidget.value = newSeed;

          // Use a microtask to restore after serialization
          const restoreFn = () => {
            if (SPECIAL_SEEDS.includes(originalValue)) {
              seedWidget.value = originalValue;
            }
          };
          setTimeout(restoreFn, 100);
        }
      }

      return origQueuePrompt.apply(this, arguments);
    };
  },
});
