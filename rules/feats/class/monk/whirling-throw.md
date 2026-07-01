---
type: Class Feat
title: "Whirling Throw"
description: "You propel your enemy away."
resource: "pf2e://feats/class/monk/whirling-throw"
tags: ["attack", "monk"]
timestamp: 2026-06-26T00:00:00Z
rarity: "common"
level: 6
category: "class"
subcategory: "monk"
action_type: "action"
actions: "1"
frequency: ""
prerequisites: []
only_level_1: false
max_takable: 
self_effect: ""
publication: "Pathfinder Player Core 2"
---

# Overview

- **Level**: 6
- **Category**: Class (monk)
- **Action**: 1 action
- **Traits**: attack, monk

## Description

**Requirements** You have a creature Grabbed or Restrained.

---

You propel your enemy away. Attempt an Athletics check against the foe's Fortitude DC. You take a –2 circumstance penalty to your check if the target is one size larger than you and a –4 circumstance penalty if it's larger than that. You gain a +2 circumstance bonus to your check if the target is one size smaller than you and a +4 circumstance bonus if it's smaller than that.

---

**Critical Success** You throw the creature any distance up to 10 feet, plus 5 feet × your Strength modifier ([[/r 10+(5*@actor.abilities.str.mod)]] feet). It takes bludgeoning damage equal to your Strength modifier plus 1d6 per 10 feet you threw it (((floor((10+(5*@actor.abilities.str.mod))/10))d6 + @actor.abilities.str.mod) bludgeoning damage). If you threw the target at least 10 feet and into a solid obstacle, use the maximum distance you could have thrown it to calculate the damage. The creature falls Prone.

**Success** As critical success, but the creature doesn't fall prone.

**Failure** You don't throw the creature.

**Critical Failure** You don't throw the creature, and it's no longer Grabbed or Restrained by you.

# Citations

[1] Pathfinder Player Core 2
[2] Source: `packs/pf2e/feats/class/monk/level-6/whirling-throw.json` (pf2e system data)
