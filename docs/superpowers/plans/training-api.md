# Training API — shared implementation interface

All routes below require bearer authentication; paths relative `/api`. Error `{detail:string}`. IDs numeric questions/sessions, string collections. Empty body is JSON `{}`. Never send another user's private data.

## Student
- GET `/training/home` => `{date,goal,completed,checked_in,streak,next_milestone,next_reward,remaining,is_admin,recent_days:[{date,checked_in}],collections:[{id,name,category,subject,count}],active_session:null|{id,mode,source,collection_id,completed,total},rewards:[{date,streak,credits}]}`.
- POST `/training/sessions` `{collection_id:""|id,source:"all"|"favorites",mode:"random"|"sequential"}` => session below. One current active session; return409 if existing until resumed/ended. Empty collection means all types.
- GET `/training/sessions/{id}` => `{id,status,mode,source,collection_id,total,completed,cards:[{id,question_id,question,answer,images:["/api/training/questions/Q/images/N"],source_info:object,category,collection_name,favorite,available,completed,rating}]}`. Only own sessions; answer available in payload but hidden by UI until reveal; authorization rechecked.
- POST `/training/sessions/{id}/cards/{card_id}/complete` `{rating:"again"|"known"|"done"}` => updated session; sequential requires first uncompleted card. Duplicate returns unchanged. Available false cards can POST same with rating done to skip but not count daily; snapshot content redacted when inaccessible.
- POST `/training/sessions/{id}/end` `{}` =>204.
- POST `/training/checkin` `{}` => `{already_checked,credits,home:<home>}`. Home.checked_in true on repeat; credits returned on repeat is original award, UI do not re-celebrate if already_checked.
- PUT `/training/questions/{id}/favorite` `{favorite:bool}` => `{favorite:bool}`.
- GET `/training/questions?mine=true&collection_id=&q=&page=1` => `{items:[question],total,page,page_size}`; `mine=false` publicly accessible+own. `favorites=true` optional.
- question `{id,collection_id,collection_name,category,question,answer,images,source_info,visibility,review_status,review_reason,version,active,favorite}`.
- POST `/training/questions` `{collection_id,question,answer}` =>question201.
- PATCH `/training/questions/{id}` `{collection_id,question,answer,version}` =>question. Approved edits become private draft; notify/confirm user.
- DELETE `/training/questions/{id}` =>204 (owner only; mark deleted to retain question IDs/progress).
- POST `/training/questions/{id}/submit` `{version}` =>question.
- POST `/training/questions/{id}/withdraw` `{version}` =>question.
- POST `/training/import/preview` multipart file .json <=config cap => `{items:[{collection_id,question,answer}],count,errors:[string]}`; errors means no mutation, UI block confirm. JSON list only (template examples supplied client).
- POST `/training/import` `{items:[{collection_id,question,answer}]}` => `{created:number}`; all-or-nothing.
- GET `/training/questions/{id}/images/{index}` authenticated FileResponse. UI must authenticated-fetch blob and revoke objectURL; raw img URL cannot send bearer.

## Admin
- GET `/admin/training/settings` => `{daily_goal,round_size,collections:[{id,name,active}],max_import_items,max_import_bytes}`.
- PATCH `/admin/training/settings` `{daily_goal,round_size}` =>settings.
- PATCH `/admin/training/collections/{id}` `{active:bool}` =>204.
- GET `/admin/training/questions?status=pending|public|all&collection_id=&q=&page=1` =>same list envelope, items include `owner_name` (normal admin cannot view other-admin submissions), revision metadata. `all` = submitted or public/official, never unsubmitted private drafts.
- POST `/admin/training/questions` `{collection_id,question,answer}` =>public official question201.
- PATCH `/admin/training/questions/{id}` `{collection_id,question,answer,version,active:bool}` =>question (official owner-null only; public owner contributions use moderation not editing someone else's unpublished text).
- POST `/admin/training/questions/{id}/review` `{version,approve:bool,reason:string}` =>question. Reject requires reason; version conflict409.
- POST `/admin/training/questions/{id}/active` `{active:bool,version}` =>question for public/official, atomic version check.
- GET `/admin/training/rewards?page=1` => `{items:[{username,date,streak,credits}],total,page,page_size}`; normal admins only normal-user rewards.
