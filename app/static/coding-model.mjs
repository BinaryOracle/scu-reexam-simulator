/** Resolve only supported question routes; invalid IDs return the practice home. */
export function codingQuestionId(hash) {
  const match = /^#view=coding\/question\/([1-9]\d*)$/.exec(hash || "");
  const id = match ? Number(match[1]) : null;
  return Number.isSafeInteger(id) ? id : null;
}

/** Apply display filters without changing the server's canonical stage ordering. */
export function filterCodingQuestions(items, { topic = "", stars = 0, order = "stage" } = {}) {
  const result = items.filter(item => (!topic || item.topic === topic) && Number(item.stars) >= Number(stars));
  return result.sort((a, b) => {
    const delta = order === "stars" ? b.stars - a.stars : order === "difficulty" ? a.difficulty - b.difficulty : 0;
    return delta || items.indexOf(a) - items.indexOf(b);
  });
}

/** Separate practice drafts from contest drafts and from other signed-in accounts. */
export const codingDraftKey = (userId, questionId, language) => `scu:${userId}:coding:${questionId}:${language}`;

/** Ignore competition callbacks and malformed practice status messages. */
export function acceptsCodingStatus(event) {
  return event?.context === "coding" && Number.isInteger(event.submission_id) && event.submission_id > 0
    && /^\d+$/.test(String(event.remote_submission_id || "")) && typeof event.status === "string" && event.status.length > 0;
}
