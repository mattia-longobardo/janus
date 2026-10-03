import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom has no layout, so it leaves scrollIntoView out; pages call it to bring editors into view.
Element.prototype.scrollIntoView ??= function scrollIntoView() {};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});
