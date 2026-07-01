---
type: Skill Feat
title: "Battle Prayer"
description: "Calling out to your deity, you recite scripture to harm a foe."
resource: "pf2e://feats/skill/battle-prayer"
tags: ["divine", "general", "skill"]
timestamp: 2026-06-26T00:00:00Z
rarity: "common"
level: 7
category: "skill"
subcategory: ""
action_type: "action"
actions: "1"
frequency: ""
prerequisites: ["master in Religion", "you follow a deity"]
only_level_1: false
max_takable: 
self_effect: ""
publication: "Pathfinder Lost Omens Gods & Magic"
---

# Overview

- **Level**: 7
- **Category**: Skill
- **Action**: 1 action
- **Prerequisites**: master in Religion, you follow a deity
- **Traits**: divine, general, skill

## Description

Calling out to your deity, you recite scripture to harm a foe. When you select this feat, choose chaos, evil, good, or law. Your choice must match one of your deity's alignment components. This action has the trait corresponding to the chosen alignment.

Attempt a religion save check against the Will DC of a foe within 30 feet. The foe is then temporarily immune to Battle Prayers from your deity for 1 day.

---

**Critical Success** You deal (ternary(gte(@actor.skills.religion.rank,4),6,2))d6 untyped damage of the chosen alignment type, or 6d6 damage if you have legendary proficiency in Religion.

**Success** You deal (ternary(gte(@actor.skills.religion.rank,4),3,1))d6 untyped damage of the chosen alignment type, or 3d6 damage if you have legendary proficiency in Religion.

**Failure** There is no effect.

**Critical Failure** The backlash of your foe's will against your prayer prevents you from using Battle Prayer again for 10 minutes.

# Citations

[1] Pathfinder Lost Omens Gods & Magic
[2] Source: `packs/pf2e/feats/skill/level-7/battle-prayer.json` (pf2e system data)
