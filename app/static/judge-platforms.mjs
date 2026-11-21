const platforms = {
  luogu: {
    label: "洛谷",
    hint: "搜索题号或题目名称，例如 P1000",
    home: "https://www.luogu.com.cn/",
    problemPath: "problem/",
    recordPath: "record/",
    standardInput: true,
    verification: true,
  },
  leetcode: {
    label: "LeetCode 中国区",
    hint: "搜索题目名称或 slug，例如 two-sum",
    home: "https://leetcode.cn/",
    problemPath: "problems/",
    recordPath: "submissions/detail/",
    standardInput: false,
    verification: false,
  },
};

export const judgePlatformOptions = Object.entries(platforms).map(([id, item]) => [id, item.label]);

export function judgePlatform(id) {
  return Object.hasOwn(platforms, id) ? platforms[id] : null;
}

export function judgeProblemUrl(id, key) {
  const config = judgePlatform(id);
  return config ? new URL(config.problemPath + encodeURIComponent(key), config.home).href : "";
}

export function judgeRecordUrl(id, key) {
  const config = judgePlatform(id);
  return config ? new URL(config.recordPath + encodeURIComponent(key) + "/", config.home).href : "";
}

export function judgeSubmitPayload(record, context, language, source) {
  const platform = record.remote_platform;
  if (!judgePlatform(platform)) throw new Error("此题未关联支持的评测平台。");
  return { context, platform, submission_id: record.id, problem_id: record.remote_problem_id,
    question_id: record.source_info?.question_id, language, source };
}
