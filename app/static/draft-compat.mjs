/** Check a code draft while remaining compatible with cached modules predating `has`. */
export function hasCodeDraft(drafts, key, getStorage) {
  if (typeof drafts.has === "function") return drafts.has(key);
  try {
    return getStorage().getItem(key) !== null;
  } catch {
    return drafts.read(key) !== "";
  }
}
