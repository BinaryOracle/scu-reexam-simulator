/** Keep drafts available in this page even when browser storage is blocked. */
export function saveDraftOnShortcut(event, save) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey || event.key.toLowerCase() !== "s") return false;
  event.preventDefault();
  save();
  return true;
}

export function createCodeDrafts(getStorage) {
  const memory = new Map();
  return {
    read(key) {
      if (memory.has(key)) return memory.get(key);
      try {
        return getStorage().getItem(key) ?? "";
      } catch {
        return "";
      }
    },
    has(key) {
      if (memory.has(key)) return true;
      try {
        return getStorage().getItem(key) !== null;
      } catch {
        return false;
      }
    },
    write(key, value) {
      try {
        getStorage().setItem(key, value);
        memory.delete(key);
        return true;
      } catch {
        memory.set(key, value);
        return false;
      }
    },
    available() {
      try {
        return Boolean(getStorage());
      } catch {
        return false;
      }
    },
  };
}
