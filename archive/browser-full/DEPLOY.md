# 브라우저만으로 배포하기 (Chrome OS, no terminal)

터미널 없이, **웹 브라우저 클릭만으로** Epsilon 웹 IDE 를 자신의 URL 로
공개하는 방법입니다. 배포된 사이트는 서버 없이 방문자의 브라우저 안에서
Epsilon 엔진(Pyodide)을 실행하므로, 배포 후에는 별도의 유지비가 없습니다.

## 방법 1 — GitHub Pages (가장 간단, 무료)

1. https://github.com/igangwoo/Epsilon 에서 우측 상단 **Fork** 를 클릭해
   자신의 계정으로 포크합니다.
2. 포크한 저장소 → **Settings** → 왼쪽 메뉴 **Pages** 로 갑니다.
3. **Source** 를 **GitHub Actions** 로 선택합니다. (Deploy from a branch 가 아님)
4. 저장소의 **Actions** 탭으로 갑니다 — 이미 "Deploy Epsilon web IDE to
   GitHub Pages" 워크플로가 자동으로 실행되고 있을 것입니다. 처음 실행되지
   않았다면, 왼쪽에서 이 워크플로를 클릭한 뒤 오른쪽의 **Run workflow** 를
   누릅니다.
5. 1~2 분 후 초록색 체크가 뜨면, **Settings → Pages** 로 돌아가 상단에
   표시된 URL 을 엽니다:
   ```
   https://<자기 GitHub 계정>.github.io/Epsilon/
   ```
6. 처음 방문할 때만 Pyodide 런타임을 ~10 MB 정도 받습니다(브라우저에 캐시됨).
   이후에는 즉시 열립니다.

수정하고 싶을 때는 GitHub 웹 편집기(`.`) 로 파일을 고쳐 커밋하면
Actions 가 자동으로 재배포합니다.

## 방법 2 — Vercel (커스텀 도메인이 쉬움)

1. 위 1 번처럼 저장소를 포크합니다.
2. https://vercel.com/new 로 갑니다. Vercel 계정이 없다면 GitHub 계정으로
   가입합니다 (모두 웹 UI 만으로).
3. **Import Git Repository** 목록에서 방금 포크한 `Epsilon` 을 찾아
   **Import** 를 누릅니다.
4. 프로젝트 설정 화면에서는 **아무것도 바꾸지 말고** 하단의
   **Deploy** 를 누릅니다 (저장소의 `vercel.json` 이 빌드 명령과 정적
   폴더를 이미 지정해 두었습니다).
5. 1~2 분 후 배포가 완료되면 `epsilon-xxx.vercel.app` URL 이 나옵니다.
   Vercel 대시보드에서 원하는 도메인을 연결할 수 있습니다.

## 사이트에서 무엇이 되나

배포된 URL 을 열면 Epsilon 웹 IDE 가 뜨고 다음이 전부 브라우저 안에서
바로 동작합니다:

- `.epsl` 파일 편집·타입검사·증명
- **✓ Formally Proven / ✓ Symbolically Verified / ≈ Numerically Verified
  / ⚠ Heuristic** 정직한 검증 상태 표시
- 증명 트리, 의존성 그래프
- 함수 그래프 (`plot f, x ∈ [-6, 6]`)
- REPL 콘솔 (`2 + 3 * 4` → `14`)
- LaTeX / Python / JSON / Lean 내보내기 (다운로드)
- 파일은 브라우저의 `localStorage` 에 저장됨 (방문자별로 프라이빗)

## 자주 있는 문제

- **한참 로딩만 됩니다**: 첫 방문은 Pyodide 를 처음 받아 10~20 초가
  걸립니다. 하단 진행 바를 확인하세요.
- **CDN 접속 오류**: 조직 네트워크가 `cdn.jsdelivr.net` 을 차단하는 경우
  다른 네트워크를 사용하거나, `boot.js` 의 `PYODIDE_CDN` 을 자신이
  호스팅하는 미러로 바꿉니다.
- **모듈이 계속 로드 상태**: 저장소의 wheel(`epsilon_math-*.whl`)이
  누락되지 않았는지 확인하세요 — GitHub Actions 가 자동으로 만들지만
  로컬 클론에서 열 때는 wheel 이 있어야 합니다.

## 라이선스

Epsilon 은 **Source-Available** 라이선스(ESAL v1.0)입니다:
개인·학술 무료, **상업 사용은 유료** — igangwoo.unite@gmail.com 로 문의.
자신의 도메인에 배포해 개인적으로 쓰거나 공부·수업에 쓰는 것은 자유입니다.

---

## 캐시에 대해 (why the asset URLs carry `?v=...`)

`index.html` 과 스크립트 파일들은 각각 따로 캐시됩니다. 그래서 예전에
방문한 적이 있는 사람은 **오래된 index.html + 새로운 스크립트** 조합을
받을 수 있습니다. 새 스크립트가 예전 HTML 에는 없는 파일을 필요로 하면,
그 사람에게만 페이지가 완전히 죽습니다 (처음 방문한 사람은 멀쩡함).

그래서 두 가지를 합니다.

1. `scripts/build_web.py` 가 자산 내용의 해시를 계산해 모든 자산 URL 에
   `?v=<build id>` 를 붙입니다. 오래된 스크립트가 새 페이지에 섞일 수
   없습니다.
2. `boot.js` 가 필요한 스크립트(`vfs.js`, `panes.js`, `app.js`)를 직접
   불러옵니다. `index.html` 의 `<script>` 태그에 의존하지 않으므로,
   아무리 오래된 HTML 이 캐시되어 있어도 부팅됩니다.

`tests/test_web_boot.py` 가 실제 브라우저에서 이 두 가지를 확인합니다.
