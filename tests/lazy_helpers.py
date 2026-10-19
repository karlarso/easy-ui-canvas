# SPDX-License-Identifier: Apache-2.0
"""Helpers for the headless-browser tests now that frames load lazily (only near the visible area).
show_all(page): "Fit window" (the whole board on screen, the old start-up view) and wait until every frame's HTML is loaded."""

SHOW_ALL = """async (fit) => {
  if (fit) document.querySelector('#zoom-menu [data-zoom="fit"]').click();
  await window.uicLoadAllFrames();
  return [...document.querySelectorAll('#board>.frame')].every(a => a.dataset.load === 'loaded');
}"""


def show_all(page, fit=True):
    """Fit the whole board and load every frame; returns True when all frames are loaded."""
    return page.evaluate(SHOW_ALL, fit)
