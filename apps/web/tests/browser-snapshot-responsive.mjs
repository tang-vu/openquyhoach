import assert from "node:assert/strict";
import { COMPLETE, INCOMPLETE } from "./browser-snapshot-support.mjs";

async function visibility(locator) {
  return locator.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const sidebar = element.closest(".sidebar").getBoundingClientRect();
    const clip = {
      top: Math.max(0, sidebar.top), bottom: Math.min(innerHeight, sidebar.bottom),
      left: Math.max(0, sidebar.left), right: Math.min(innerWidth, sidebar.right),
    };
    const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    return {
      visible: rect.width > 0 && rect.height > 0 && rect.top >= clip.top &&
        rect.bottom <= clip.bottom && rect.left >= clip.left && rect.right <= clip.right,
      hit: hit === element || element.contains(hit),
      scrollDelta: rect.bottom - (clip.bottom - 12),
    };
  });
}

export async function revealSnapshotChoice(harness, ui, complete = true) {
  const { page } = harness;
  const choice = ui.button(complete ? COMPLETE : INCOMPLETE);
  const errors = page.locator('section[aria-label="Metadata snapshot"] .error');
  const sidebar = await page.locator(".sidebar").boundingBox();
  assert.ok(sidebar, "The responsive sidebar must be visible");
  await page.mouse.move(sidebar.x + sidebar.width / 2, sidebar.y + Math.min(sidebar.height / 2, 100));
  for (let attempt = 0; attempt < 8; attempt++) {
    const state = await visibility(choice);
    const failureStates = await Promise.all((await errors.all()).map(visibility));
    if (state.visible && state.hit && failureStates.every((failure) => failure.visible)) return;
    // Real wheel input scrolls the responsive sidebar; no forced click, injected
    // CSS, element repositioning or programmatic focus makes the choice reachable.
    await page.mouse.wheel(0, state.scrollDelta);
    await page.waitForTimeout(100);
  }
  const state = await visibility(choice);
  assert.ok(state.visible, "Final snapshot choice must be fully inside the viewport and sidebar");
  assert.ok(state.hit, "Final snapshot choice must receive a hit at its center");
  for (const error of await errors.all())
    assert.ok((await visibility(error)).visible, "Every declared manifest failure must be visible beside the choice");
}

export async function tabToSnapshotChoice(harness, ui, complete = true) {
  const { page } = harness;
  const choice = ui.button(complete ? COMPLETE : INCOMPLETE);
  let focused = false;
  for (let attempt = 0; attempt < 32; attempt++) {
    await page.keyboard.press("Tab");
    focused = await choice.evaluate((element) => document.activeElement === element);
    if (focused) break;
  }
  assert.ok(focused, "Ordinary Tab navigation must reach the final snapshot choice");
  await revealSnapshotChoice(harness, ui, complete);
  assert.ok(await choice.evaluate((element) => document.activeElement === element),
    "Scrolling must preserve keyboard focus on the final snapshot choice");
  assert.equal(await choice.isEnabled(), true);
}
