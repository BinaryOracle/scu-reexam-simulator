"""Optional browser acceptance against an isolated running instance (requires playwright).

python -X utf8 tests/course_browser.py http://127.0.0.1:8765
Use only with the disposable course QA database and its default root/root account.
"""
import json
import subprocess
import sys
import time
from pathlib import Path
import imageio_ffmpeg
from playwright.sync_api import sync_playwright, expect


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765'
    output = Path('output/course-qa')
    output.mkdir(parents=True, exist_ok=True)
    clip = output.resolve() / 'clip.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24', '-t', '3',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(clip)], check=True)
    camera = output.resolve() / 'camera.y4m'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24', '-t', '2',
        '-pix_fmt', 'yuv420p', str(camera)], check=True)
    errors = []
    title = '课程验收 · 数据结构 ' + str(time.time_ns())
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=[
            '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
            '--use-file-for-fake-video-capture=' + str(camera),
            '--autoplay-policy=no-user-gesture-required'])
        admin = browser.new_context(viewport={'width': 1365, 'height': 960}, permissions=['camera', 'microphone'])
        page = admin.new_page()
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.goto(base + '/admin')
        page.locator('#username').fill('root')
        page.locator('#password').fill('root')
        page.locator('#loginButton').click()
        expect(page.locator('#app')).to_be_visible()
        page.get_by_role('button', name='课程管理', exact=True).click()
        page.get_by_text('新建课程', exact=True).click()
        page.get_by_label('课程名称', exact=True).fill(title)
        page.get_by_label('课程简介', exact=True).fill('通过课程资料、视频讲解与直播，系统复习数据结构。')
        page.get_by_label('发布课程', exact=True).check()
        page.get_by_role('button', name='创建课程', exact=True).click()
        page.get_by_label('课节名称', exact=True).fill('第一节 · 线性表与复杂度分析')
        page.get_by_label('课节简介', exact=True).fill('掌握顺序表与链表的特点，通过典型题目理解时间复杂度。')
        page.get_by_role('button', name='保存课节', exact=True).click()
        expect(page.get_by_role('heading', name='第一节 · 线性表与复杂度分析')).to_be_visible()
        page.get_by_label('选择课程资料').set_input_files({
            'name': '第一节讲义.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF-QA-material'})
        page.get_by_role('button', name='上传资料', exact=True).click()
        expect(page.get_by_text('第一节讲义.pdf', exact=True)).to_be_visible()
        page.get_by_role('button', name='录播', exact=True).click()
        page.get_by_label('选择 MP4 / WebM 视频').set_input_files(str(clip))
        page.get_by_role('button', name='上传录播', exact=True).click()
        expect(page.get_by_text('clip.mp4', exact=True)).to_be_visible()
        cid, lid = page.url.split('/')[-2:]
        token = page.evaluate("sessionStorage.getItem('token')")
        response = admin.request.post(base + '/api/admin/users', headers={'Authorization': 'Bearer ' + token},
            data={'username': 'course-qa-' + str(int(time.time())), 'password': 'password123'})
        assert response.ok, response.text()
        student_name = response.json()['username']
        learner_token = admin.request.post(base + '/api/login', data={
            'username': student_name, 'password': 'password123'}).json()['token']
        learner = browser.new_context(viewport={'width': 1365, 'height': 960})
        learner.add_init_script('sessionStorage.setItem("token",' + json.dumps(learner_token) + ')')
        student = learner.new_page()
        student.on('pageerror', lambda err: errors.append(str(err)))
        student.goto(base + '/#view=courses')
        expect(student.locator('#courses').get_by_role('heading', name='课程.')).to_be_visible()
        expect(student.get_by_text(title, exact=True)).not_to_be_visible()
        page.get_by_text('观看权限', exact=True).click()
        page.get_by_label('搜索学员（用户名或邮箱）').fill(student_name)
        page.get_by_role('checkbox', name=student_name, exact=True).check()
        page.get_by_role('button', name='保存观看权限', exact=True).click()
        expect(page.get_by_text('观看权限已保存', exact=True)).to_be_visible()
        page.screenshot(path=str(output / 'course-access.png'), full_page=True)
        page.get_by_text('观看权限', exact=True).click()
        student.goto(base + f'/#view=courses/{cid}/{lid}')
        expect(student.get_by_role('heading', name='第一节 · 线性表与复杂度分析')).to_be_visible()
        with student.expect_download() as download:
            student.get_by_role('button', name='下载资料', exact=True).click()
        assert download.value.suggested_filename == '第一节讲义.pdf'
        student.get_by_role('button', name='录播', exact=True).click()
        student.get_by_role('button', name='播放录播', exact=True).click()
        student.wait_for_function('document.querySelector("#courseMedia video")?.readyState >= 2')
        # Set a near-future schedule and exercise unattended start/end after capture authorization.
        page.get_by_text('编辑课节与直播排期', exact=True).click()
        # datetime-local has minute precision, so use the API to set second precision for acceptance.
        starts = time.time() + 12
        response = admin.request.put(base + f'/api/admin/courses/{cid}/lessons/{lid}', headers={
            'Authorization': 'Bearer ' + token}, data={'title': '第一节 · 线性表与复杂度分析',
            'description': '掌握顺序表与链表的特点，通过典型题目理解时间复杂度。', 'position': 1,
            'live_start': starts, 'live_end': starts + 28})
        assert response.ok, response.text()
        page.reload()
        page.get_by_role('button', name='直播', exact=True).click()
        page.get_by_role('button', name='摄像头 + 麦克风', exact=True).click()
        expect(page.locator('#courseMedia [role="status"]')).to_contain_text('已就绪', timeout=10000)
        student.get_by_role('button', name='直播', exact=True).click()
        expect(page.locator('#courseMedia [role="status"]')).to_contain_text('正在直播', timeout=20000)
        expect(student.get_by_role('button', name='观看直播', exact=True)).to_be_visible(timeout=25000)
        student.get_by_role('button', name='观看直播', exact=True).click()
        student.wait_for_function('document.querySelector("#courseMedia video")?.readyState >= 2', timeout=18000)
        student.screenshot(path=str(output / 'student-live.png'), full_page=True)
        expect(page.get_by_role('button', name='结束直播并保存', exact=True)).not_to_be_visible(timeout=45000)
        expect(page.get_by_text('直播已结束，回放已保存', exact=True)).to_be_visible(timeout=15000)
        student.get_by_role('button', name='录播', exact=True).click()
        expect(student.get_by_role('button', name='播放回放', exact=True)).to_be_visible(timeout=12000)
        student.get_by_role('button', name='播放回放', exact=True).click()
        student.wait_for_function('document.querySelector("#courseMedia video")?.readyState >= 2', timeout=15000)
        student.screenshot(path=str(output / 'student-replay.png'), full_page=True)
        page.screenshot(path=str(output / 'admin.png'), full_page=True)
        student.set_viewport_size({'width': 390, 'height': 844})
        student.wait_for_function('document.querySelector(".main-shell").getBoundingClientRect().left <= 1')
        student.screenshot(path=str(output / 'mobile.png'), full_page=True)
        assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
    print('PASS: authoring, uploads, download, video playback, scheduled browser capture, live viewing, automatic replay, mobile layout; no page errors')


if __name__ == '__main__':
    main()
