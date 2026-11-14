/** Stores the last verified Luogu account in user-scoped browser storage. */
export function readLuoguConnection(storage, userId) {
  if (!userId) return "";
  try {
    return storage.getItem(`scu:${userId}:luogu-account`) || "";
  } catch (error) {
    return "";
  }
}

/** Saves or clears the last verified Luogu account without storing credentials. */
export function writeLuoguConnection(storage, userId, account) {
  if (!userId) return;
  try {
    const key = `scu:${userId}:luogu-account`;
    if (account) storage.setItem(key, account);
    else storage.removeItem(key);
  } catch (error) {
    // Storage may be unavailable; bridge detection still works for this page.
  }
}
