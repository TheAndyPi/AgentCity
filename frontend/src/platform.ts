import type { Settings } from "./api/types";

type ShortcutAction = keyof Settings["shortcuts"];

export const isMac = (() => {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & {
    userAgentData?: { platform?: string };
  };
  const platform =
    nav.userAgentData?.platform || nav.platform || nav.userAgent || "";
  return /mac|iphone|ipad|ipod/i.test(platform);
})();

const keyNames: Record<string, string> = {
  Space: "Space",
  Equal: "=",
  Minus: "−",
  ArrowUp: "↑",
  ArrowDown: "↓",
  ArrowLeft: "←",
  ArrowRight: "→",
  Enter: "Enter",
  Comma: ",",
  Period: ".",
  BracketLeft: "[",
  BracketRight: "]",
  PageUp: "Page Up",
  PageDown: "Page Down",
};

export function chordParts(chord: string) {
  return chord.split("+").map((part) => {
    if (part === "Mod") return isMac ? "⌘" : "Ctrl";
    if (part === "Alt") return isMac ? "⌥" : "Alt";
    if (part === "Shift") return isMac ? "⇧" : "Shift";
    if (part.startsWith("Key")) return part.slice(3);
    if (part.startsWith("Digit")) return part.slice(5);
    return keyNames[part] ?? part;
  });
}

export const formatChord = (chord: string) =>
  chordParts(chord).join(isMac ? " " : " + ");

export const shortcutChoices: Record<ShortcutAction, string[]> = {
  pause: ["Space", "KeyP", "KeyK", "Enter"],
  zoom_in: ["Mod+Equal", "Equal", "KeyE", "PageUp", "BracketRight"],
  zoom_out: ["Mod+Minus", "Minus", "KeyQ", "PageDown", "BracketLeft"],
  rotate_left: ["Mod+ArrowLeft", "Shift+ArrowLeft", "Comma", "KeyZ"],
  rotate_right: ["Mod+ArrowRight", "Shift+ArrowRight", "Period", "KeyX"],
  pan_up: ["ArrowUp", "KeyW", "KeyI"],
  pan_down: ["ArrowDown", "KeyS", "KeyK"],
  pan_left: ["ArrowLeft", "KeyA", "KeyJ"],
  pan_right: ["ArrowRight", "KeyD", "KeyL"],
};
