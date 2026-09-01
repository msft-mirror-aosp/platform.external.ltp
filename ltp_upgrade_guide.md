# LTP Monthly Update 教學手冊 — 以 20260801 升級為例

本文件記錄了 Android `external/ltp` 從 20260703 升級至 20260801 的完整流程，
包含所有 terminal 指令、遭遇的問題與解決方式。可作為未來每月 LTP 升級的操作參考。

---

## 目錄

1. [前置準備](#1-前置準備)
2. [使用 External Updater 執行升級](#2-使用-external-updater-執行升級)
3. [解決 Merge 衝突](#3-解決-merge-衝突)
4. [更新 Build System](#4-更新-build-system-genbp)
5. [本地編譯驗證](#5-本地編譯驗證)
6. [處理編譯失敗 — PEDIT 宏衝突](#6-處理編譯失敗--pedit-宏衝突)
7. [整理 Commit 歷史與上傳 Gerrit](#7-整理-commit-歷史與上傳-gerrit)
8. [使用 ABTD 進行雲端測試驗證](#8-使用-abtd-進行雲端測試驗證)
9. [處理 Presubmit 測試失敗 — Loop Device 競爭](#9-處理-presubmit-測試失敗--loop-device-競爭問題)
10. [向 Upstream 社群投遞 Patch](#10-向-upstream-社群投遞-patch)
11. [將 Upstream Patch 回填至 Android Gerrit](#11-將-upstream-patch-回填至-android-gerrit-fromlist)
12. [處理 Upstream Review Feedback](#12-處理-upstream-review-feedback-patch-v2)
13. [附錄：常用工具與注意事項](#13-附錄常用工具路徑與注意事項)

---

## 1. 前置準備

### 1.1 同步 Android Source Tree

```bash
cd ~/dev/aosp-main
repo sync external/ltp
```

### 1.2 初始化建置環境

```bash
source build/envsetup.sh
lunch aosp_cf_x86_64_phone-trunk_staging-eng
```

### 1.3 確認當前版本

```bash
cd external/ltp
cat METADATA
git log --first-parent -n 5 --oneline
```

---

## 2. 使用 External Updater 執行升級

### 2.1 檢查可用更新

```bash
cd ~/dev/aosp-main
tools/external_updater/updater.sh check external/ltp
```

### 2.2 執行升級

```bash
tools/external_updater/updater.sh update \
    --no-upload \
    --keep-local-changes \
    external/ltp
```

> **重要**：
> - `--keep-local-changes` 保留 `patches/` 中的 Android 專屬 patch
> - `--no-upload` 防止自動觸發 `repo upload`

### 2.3 升級到特定 upstream commit

```bash
tools/external_updater/updater.sh update \
    --no-upload \
    --keep-local-changes \
    --custom-version <upstream_commit_sha> \
    external/ltp
```

---

## 3. 解決 Merge 衝突

External Updater 使用 `git merge`，當 Android 有本地修改時可能產生衝突。

### 3.1 檢視衝突狀態

```bash
cd external/ltp
git status
```

### 3.2 常見衝突類型與解法

#### (a) patches/ 中的 patch 與 upstream 衝突

若 upstream 已包含等效修復，移除過時的 patch：

```bash
git log --oneline <old_tag>..<new_tag> -- <conflicting_file>
git rm patches/LIB-0001-ANDROID-loop-device-creation-retry.patch
git checkout <new_upstream_tag> -- lib/tst_device.c
```

#### (b) .gitmodules 衝突

Android 不使用 submodules：

```bash
git rm .gitmodules
```

### 3.3 完成 Merge

```bash
git add -A
git commit --no-edit
```

---

## 4. 更新 Build System (gen.bp)

每次升級後必須重新生成 Android 建置規則。

```bash
rm -rf android/tools/dump/*.dump
./android/tools/gen_android_build.sh --update
git diff gen.bp
git add gen.bp android/include/config.h
git commit --amend --no-edit
```

---

## 5. 本地編譯驗證

```bash
source build/envsetup.sh
lunch aosp_cf_x86_64_phone-trunk_staging-eng
m ltp_runtests            # 基礎模組
m ltp_cve-2026-46331      # 特定 CVE 測試
m ltp_execveat02          # 特定測試
```

> **警告**：絕對禁止在編譯未通過的情況下上傳任何 CL 至 Gerrit。

---

## 6. 處理編譯失敗 — PEDIT 宏衝突

### 6.1 問題

LTP 20260801 的 `cve-2026-46331` 測試使用 `tc_pedit.h` 的 `HAVE_ENUM_PEDIT` 宏。
Android Bionic kernel headers 已定義同名 enum，導致重複定義。

### 6.2 修復

在 `android/include/config.h` 中預先定義宏：

```c
/* Bionic kernel headers already define these enums in
 * <linux/tc_act/tc_pedit.h>. Define these macros so that
 * lapi/tc_pedit.h skips its fallback definitions. */
#define HAVE_ENUM_PEDIT_HDR_TYPE_NETWORK 1
#define HAVE_ENUM_PEDIT_CMD_SET 1
```

### 6.3 驗證與提交

```bash
m ltp_cve-2026-46331
git add android/include/config.h
git commit -m "ANDROID: ltp: Define HAVE_ENUM_PEDIT macros to avoid compilation failure

Bug: 542167984
Test: m ltp_cve-2026-46331"
```

---

## 7. 整理 Commit 歷史與上傳 Gerrit

### 7.1 CL 鏈結構

| # | 類型 | 說明 |
|---|------|------|
| 1 | `ANDROID:` | Align LTP history with upstream |
| 2 | `ANDROID:` | Remove local loop device retry patch |
| 3 | Merge | LTP 20260801 update (含 gen.bp) |
| 4 | `ANDROID:` | Define HAVE_ENUM_PEDIT macros |
| 5 | `FROMLIST:` | Upstream backoff polling patch |

### 7.2 建立開發分支與上傳

```bash
git checkout -b 20260801-ltp goog/main
# ... (整理完 commit 歷史後)
repo upload --yes --cbr .
```

> **注意**：Android 平台變更必須上傳至內部 Gerrit
> (`googleplex-android-review.git.corp.google.com`)。
> 嚴格禁止上傳至公開 AOSP Gerrit。

---

## 8. 使用 ABTD 進行雲端測試驗證

### 8.1 設定 alias

```bash
alias abtd=/google/bin/releases/atp-dev/tools/forrest-mpm/forrest-mpm/forrest.par
```

### 8.2 僅編譯驗證（Build-only）

```bash
abtd build \
    --extra_build_targets=aosp_cheetah-trunk_staging-userdebug \
    th:cl:<CL_NUMBER>:test_suites_x86_64-next:git_main
```

### 8.3 執行實機 VTS 測試

```bash
abtd -l remote -b git_main atest \
    https://googleplex-android-review.git.corp.google.com/c/platform/external/ltp/+/<CL> \
    vts_ltp_test_x86_64:syscalls.chdir01_64bit
```

### 8.4 查看結果

```
http://go/forrest-run/<RUN_ID>
```

> **重要**：Build-only 只驗證編譯，不會執行 VTS 測試。
> 必須使用 `abtd atest` 才能捕捉 runtime 問題。

---

## 9. 處理 Presubmit 測試失敗 — Loop Device 競爭問題

### 9.1 問題

AVD 模擬器中 loop device 節點建立是非同步的。`LOOP_CTL_GET_FREE` 回傳後
`/dev/loopX` 尚未出現，LTP 立即 `stat()` 會遇到 `ENOENT`。

### 9.2 修復：指數退避輪詢

在 `lib/tst_device.c` 中引入 backoff polling：

```c
/* tst_find_free_loopdev() */
if (path) {
    unsigned int usec = 1000; /* 1ms */
    for (i = 0; i < 30; i++) {
        path_set = set_dev_loop_path(rc, path, path_len);
        if (!path_set)
            break;
        if (i < 29) {
            usleep(usec);
            usec = usec * 2 < 100000 ? usec * 2 : 100000;
        }
    }
    if (path_set)
        tst_brkm(TBROK, NULL, "Could not stat loop device %i", rc);
}

/* tst_attach_device() */
unsigned int usec = 1000;
for (i = 0; i < 15; i++) {
    dev_fd = open(dev, O_RDWR);
    if (dev_fd >= 0)
        break;
    if (i < 14) {
        usleep(usec);
        usec = usec * 2 < 100000 ? usec * 2 : 100000;
    }
}
```

### 9.3 驗證

```bash
m ltp_cve-2026-46331
```

---

## 10. 向 Upstream 社群投遞 Patch

### 10.1 準備 Patch

```bash
cd ~/dev/aosp-main/external/ltp
git commit lib/tst_device.c -F upstream_commit_msg.txt
git format-patch -1 HEAD -o /tmp/
```

### 10.2 格式檢查

```bash
scripts/checkpatch.pl /tmp/0001-*.patch
```

### 10.3 參考 LTP Agent 規範

```bash
git clone --depth 1 https://github.com/linux-test-project/ltp-agent.git /tmp/ltp-agent
```

規範重點：
- 禁止固定長度 `sleep()`，須用指數退避
- Subject 50~72 字元，祈使句
- Body 每行 <= 72 字元
- 必須有 `Signed-off-by:`

### 10.4 清理 Android 標記

移除 `FROMLIST:`、`Bug:`、`Test:`、`Change-Id:` 後再投遞。

### 10.5 發送

```bash
git send-email \
    --to="ltp@lists.linux.it" \
    --cc="wakel@google.com" \
    --confirm=never \
    /tmp/0001-*.patch
```

---

## 11. 將 Upstream Patch 回填至 Android Gerrit (FROMLIST)

### 11.1 使用 b4 下載

```bash
git clone --depth 1 https://git.kernel.org/pub/scm/utils/b4/b4.git /tmp/b4-src
cd /tmp/b4-src && git submodule update --init --recursive --depth 1
pip install --index-url=https://pypi.org/simple dkimpy

PYTHONPATH="/tmp/b4-src/src:/tmp/b4-src/patatt/src:/tmp/b4-src/liblore/src:/tmp/b4-src/ezgb/src" \
    python3 /tmp/b4-src/src/b4/command.py am -o /tmp/ \
    https://lore.kernel.org/ltp/<message-id>/
```

### 11.2 套用至 Android 分支

```bash
cd ~/dev/aosp-main/external/ltp
git am /tmp/<downloaded>.mbx
```

### 11.3 修改 Commit Message

格式：

```
FROMLIST: lib: Use backoff polling to wait for loop device nodes

<body>

Link: https://lore.kernel.org/ltp/<message-id>/
Bug: 542167984
Test: atest vts_ltp_test_x86_64:syscalls.chdir01_64bit
Test: m ltp_cve-2026-46331
Signed-off-by: Wake Liu <wakel@google.com>
Change-Id: <必須放在最後一行>
```

> **重要**：
> - `FROMLIST:` 前綴 = 來自 upstream 郵件列表的臨時補丁
> - `Link:` 指向 lore.kernel.org 原始討論
> - `Test:` 必須寫具體 `atest` 指令，禁止 `Test: Presubmit`
> - `Change-Id:` 必須在最後一行，否則 hook 會重新生成

### 11.4 上傳

```bash
repo upload --yes --cbr .
```

---

## 12. 處理 Upstream Review Feedback (PATCH v2)

### 12.1 確認基底一致性

```bash
git diff <upstream_merge_commit> <android_base> -- lib/tst_device.c
# 輸出為空 = 一致，可在 Android repo 上直接改
# 有差異 = 必須在 upstream clone 上獨立開發
```

### 12.2 修改、驗證、產生 v2

```bash
vim lib/tst_device.c
m ltp_cve-2026-46331
git commit --amend -a --no-edit
git format-patch --subject-prefix="PATCH v2" -1 HEAD -o /tmp/
# 清理 Android 標記
```

### 12.3 發送 v2

```bash
git send-email \
    --to="ltp@lists.linux.it" \
    --cc="wakel@google.com" \
    --in-reply-to="<original-message-id>" \
    --confirm=never \
    /tmp/0001-*.patch
```

### 12.4 同步更新 Android Gerrit

```bash
git commit --amend -F commit_msg_with_same_changeid.txt
repo upload --yes --cbr .
```

---

## 13. 附錄：常用工具路徑與注意事項

### 13.1 工具路徑

| 工具 | 路徑 |
|------|------|
| External Updater | `tools/external_updater/updater.sh` |
| ABTD CLI | `/google/bin/releases/atp-dev/tools/forrest-mpm/forrest-mpm/forrest.par` |
| Buganizer CLI | `/google/bin/releases/issues-cli/issues` |
| gen_android_build | `android/tools/gen_android_build.sh` |

### 13.2 Buganizer 操作

```bash
# 搜尋 component
/google/bin/releases/issues-cli/issues search-components --query "ltp"

# 建立 Bug
/google/bin/releases/issues-cli/issues create \
    --component_id=176043 \
    --title="LTP: <title>" \
    --description_file=<file>

# 新增評論
/google/bin/releases/issues-cli/issues comment \
    --issue_id <BUG_ID> \
    --comment_file <file>
```

### 13.3 Commit Message 格式對照

| 場景 | 前綴 | 必要欄位 |
|------|------|----------|
| Android 客製化 | `ANDROID:` | `Bug:`, `Test:`, `Change-Id:` |
| Upstream 臨時補丁 | `FROMLIST:` | `Link:`, `Bug:`, `Test:`, `Change-Id:` |
| 投遞 upstream | 無前綴 | `Signed-off-by:` |
| Upstream 已合入 | `UPSTREAM:` | `Link:`, `Bug:`, `Test:`, `Change-Id:` |

### 13.4 Upstream 投遞工作流

```
理想流程（檔案有 Android 客製化時）：
  1. Clone upstream LTP -> 乾淨基底上開發 -> 產生 patch
  2. 投遞 upstream 審查
  3. Cherry-pick 回 Android repo，加上 FROMLIST/Bug/Test/Change-Id

簡化流程（確認檔案基底一致時）：
  1. 在 Android repo 上直接開發
  2. 產生 patch 時清除 Android 標記後投遞 upstream
  3. 同一 commit amend 後上傳 Android Gerrit
```

### 13.5 嚴格禁止事項

1. 指稱內部 Gerrit 時嚴格禁止使用 "AOSP"，必須使用 "Android"
2. 禁止未經編譯驗證就上傳 CL
3. 禁止將 Android 平台專案上傳至公開 AOSP Gerrit
4. `Test:` 必須寫具體 `atest` 指令，禁止 `Test: Presubmit`
