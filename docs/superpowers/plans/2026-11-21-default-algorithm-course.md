# 默认算法入门课程实施计划

**目标：** 将“算法刷题速成”免费内容整理成默认公开课程，学员能在本站阅读、下载和记录学习进度。

**实现：** 复用现有章节、课时和 Markdown 资源表。课程清单及独立编写的学习笔记放在 `app/assets/courses/algorithm-beginner/`；`app/services/default_courses.py` 在数据库初始化事务中一次性导入，使用 `app_settings` 标记，文件失败时清理本次导入的资源。无新数据库版本或运行时网络依赖。

**约束：** 保留现有未提交修改；不启动常驻服务；不访问会员接口；不覆盖管理员编辑；删除课程后不自动重建。

- [x] 编写 `tests/test_default_courses.py`，覆盖默认公开课程、42 个免费课时、鉴权阅读与进度、已有数据升级、重复初始化、编辑保留、删除保留、导入失败回滚。
- [x] 运行新测试，确认因缺少默认课程失败。
- [x] 整理 42 个免费课时的 Markdown 学习笔记与 `catalog.json`；每课包含原文链接、目标、知识说明和自测任务，技术课补充独立编写的示例或推导。
- [x] 添加默认课程导入服务；在 `app/db.py` 的初始化事务末尾调用，文件清理上下文包裹数据库提交。
- [x] 更新已有公开课程列表测试，允许额外的默认公开课程且仍严格校验草稿不可见。
- [x] 更新 README 与部署文档，说明默认课程、来源范围、一次性导入及备份路径。
- [x] 执行 `.venv/bin/python -m pytest -q tests/test_default_courses.py tests/test_course_learning.py tests/test_live.py` 与 `git diff --check`；核对全部课时与来源清单对应且排除会员条目。
