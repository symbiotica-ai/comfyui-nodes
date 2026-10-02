## Title
Prompts node multi select

## Problem
in order to use multiple prompt i have to duplicate the node many times

## Solution
selection box similar to Recipes node, select multiple prompts will output them individually, the name of the output will be the prompt's file name

## Variables
local comfy ui installation
bakery-final-03.json

## Implementation Notes
reuse the Recipes node checkbox

## Workflow
short plan and aproval
build
test

## Deliverables
new version of the node
new workflow (04) where you replace the many nodes with the new one

## Definition Of Done
Prompts node has a selection box similar to the Recipes node in the sidebar, allowing multi prompts selection
output multiple prompts individually
dynamic output number based on how many prompts are selected
