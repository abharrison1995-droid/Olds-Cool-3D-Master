---
name: 3D MASTER:2005
description: A compact spline-modeling workbench with early-2000s desktop character.
colors:
  primary: "#D98435"
  neutral-bg: "#B9BDC0"
  neutral-field: "#E1E3E2"
  neutral-ink: "#171B20"
  workspace-rail: "#3C444C"
  viewport-graphite: "#282E35"
  control-raised: "#C5C9CA"
typography:
  body:
    fontFamily: "Tahoma"
    fontSize: "12px"
components:
  button-raised:
    backgroundColor: "{colors.control-raised}"
    textColor: "{colors.neutral-ink}"
    padding: "4px 9px"
  input-inset:
    backgroundColor: "{colors.neutral-field}"
    textColor: "{colors.neutral-ink}"
    padding: "3px 4px"
  workspace-tab:
    backgroundColor: "#737C84"
    textColor: "#F5F5F2"
    padding: "6px 15px 5px"
  workspace-tab-active:
    backgroundColor: "#C6C9C9"
    textColor: "{colors.neutral-ink}"
    padding: "6px 15px 5px"
  selected-row:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.neutral-ink}"
    padding: "1px 3px"
---

# Design System: 3D MASTER:2005

## Overview

**Creative North Star: “The Steel-and-Graphite Workbench”**

The user’s direction is “Blender meets the early 2000s.” Treat the editor as a serious native modeling tool: compact task workspaces, linked editing areas, cool steel-gray controls, and a dark graphite viewport. Use the amber accent as a single clear signal for active tools, selected objects, and focused editing states.

The interface favors direct access to the scene, properties, and timeline over decorative framing. Beveled borders and dark panel title bands establish depth; the viewport stays visually distinct from the light editing surfaces. Keep the controls dense, tactile, and legible, with square corners and immediate state changes.

**Key Characteristics:**

- Compact, resizable work areas around a large 3D viewport.
- Cool steel-gray chrome around a graphite canvas.
- Amber marks selection and active editing state.
- Raised buttons, inset fields, crisp borders, and square corners.
- Tahoma at 12px for the general interface; no decorative motion.

## Colors

The palette uses cool, near-neutral steel surfaces and one warm amber interaction color. The timeline uses its own functional colors: cyan key markers and a red playhead.

### Primary

- **Workbench Amber**: selection, active tools, focused list rows, and splitter hover. Keep it tied to a real interactive state.

### Neutral

- **Cool Steel Canvas**: the main editing surface and overall panel background.
- **Inset Field Gray**: editable fields and numeric controls.
- **Graphite Ink**: default text and the readable foreground on light controls.
- **Dark Steel Rail**: the workspace-tab track and framing between work areas.
- **Graphite Viewport**: the 3D canvas, visually separated from the form controls.
- **Beveled Control Face**: raised buttons and tool controls.

**The One Amber Signal Rule.** Use amber for a current selection or active state. Do not turn it into a general decoration color.

## Typography

**Body Font:** Tahoma (Qt’s configured sans-serif fallback if unavailable).

**Character:** compact, direct interface text with familiar desktop-software proportions. Keep labels readable at the same scale as field values; use weight, not a display face, to distinguish workspace and area titles.

### Hierarchy

- **Body** (regular, 12px): default control text, menus, labels, and property values.
- **Label** (bold, 12px): selected workspace and dock-area titles.

## Layout

The editor is a tiled workbench: menu row, workspace tabs, one compact workspace tool strip, a large central viewport, stacked Outliner and Properties areas at right, and a full-width timeline below. Six-pixel splitters separate resizable panels. Keep the selected object visible in both the viewport and Outliner, with its editable values immediately available in Properties.

At narrow widths, compress the Properties tab rail and keep vector fields and bone actions within the pane. The 1280×820 and 1440×900 preview captures show all four property tabs and all three transform values without horizontal scrolling. Preserve this behavior when the editor is resized; display-scale coverage beyond these captures remains a product constraint.

## Elevation & Depth

The system uses no drop shadows. Depth comes from tonal panel bands and one-pixel bevels: light top/left edges make a control feel raised, while dark top/left edges make a field feel inset. The viewport gains separation from its graphite surface rather than a floating card treatment.

**The Bevel Is the Depth Rule.** Use light and dark border edges to distinguish raised and inset hardware; do not add ambient card shadows.

## Shapes

Keep panel edges and controls square. Use crisp one-pixel borders with light and dark sides for native raised or inset states. Workspace tabs use a stronger top edge for the active tab, and area headers use a continuous dark steel band. Avoid pill controls and rounded cards.

## Components

### Buttons

Buttons feel like tactile desktop controls. Use a raised face with a light top/left bevel and a darker bottom/right edge. Hover lightens the face; pressed and checked states invert the bevel; keyboard focus gets a darker amber border. Disabled buttons use a muted steel face and lower-contrast text.

### Inputs / Fields

Numeric and text fields use a pale inset surface, dark text, and opposing border tones. Preserve spin buttons where they provide useful numeric adjustment. Focus changes the border to a darker amber tone without adding a glow.

### Navigation

The main menu stays at the top. The five workspace tabs sit in a dark rail; the active tab uses a light face, bold text, and a narrow amber top edge. Keep the workspace-specific tool strip directly below the tabs.

### Areas and Splitters

Viewport, Outliner, Properties, and Timeline each receive a dark title band with compact collapse and menu controls. Splitter handles remain visible and respond to hover with the active amber. These are working resizable areas, not decorative cards.

### Selection and Timeline

Selected scene rows use amber fill with dark text. Timeline key markers stay cyan, the selected key marker uses warm orange, and the current-frame line stays red. Keep these colors scoped to their timeline meanings.

### Viewport

The center canvas is graphite with a fine perspective floor grid. Rendered geometry remains the focal point; selection bounds and transform gizmos appear only when the scene state calls for them.

## Do's and Don'ts

### Do:

- **Do** keep the viewport, Outliner, Properties, and Timeline visually distinct and directly accessible.
- **Do** use amber only for an active tool, selected object, focus state, or splitter hover.
- **Do** preserve bevel direction so raised buttons and inset fields read differently.
- **Do** keep every transform value and Properties tab visible at compact pane widths.
- **Do** use the real scene and real editing state in previews.

### Don't:

- **Don't** add glass, ambient shadows, rounded cards, or decorative texture to the editor chrome.
- **Don't** use amber as a background decoration or as a substitute for timeline key colors.
- **Don't** hide controls behind horizontal scrolling when the pane can be compacted.
- **Don't** imply unsupported modeling or export features through the visual language.
