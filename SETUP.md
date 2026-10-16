# Setup, no terminal needed

Time: about 15 minutes. You need your GitHub and Netlify logins. Repo: `tmbstartkleen-svg/Claude_Sports_TMB`.

## 1. Put the files in the repo
1. Double-click `slate-pipeline.zip` in Downloads to unzip it. Open the new `slate-pipeline` folder.
2. The `.github` folder is hidden on a Mac. In Finder press **Cmd + Shift + .** (period) to show hidden files. Without this the automation never uploads.
3. On GitHub open the repo, click **Add file, then Upload files**.
4. Select everything INSIDE `slate-pipeline` (index.html, README.md, SETUP.md, netlify.toml, `pipeline`, `.github`) and drag it into the browser window. Drag the contents, not the `slate-pipeline` folder itself.
5. Wait for all files to finish uploading, write "Add slate pipeline" in the box, click **Commit changes**.
6. Check: the repo front page should show `.github`, `pipeline`, `index.html`, `netlify.toml`.

## 2. Let the automation save its results
Repo, **Settings, Actions, General**, scroll to **Workflow permissions**, choose **Read and write permissions**, click **Save**.

## 3. Run it once
Repo, **Actions** tab. If asked, click **I understand my workflows, enable them**. Click **Build slate** on the left, then **Run workflow**, then the green button. Wait 1 to 3 minutes. (It then repeats on its own: full runs at 15:00 and 23:00 UTC, line snapshots every 30 minutes in the evening.) A green check means it worked; a red X means click it and send me a screenshot of the error.
After it works, the repo gets new files: `slate.json`, `history.json`, `picks.json`, `record.json`.

## 4. Put it on the internet (Netlify)
1. netlify.com, **Add new site, Import an existing project, GitHub**, pick `Claude_Sports_TMB`.
2. Leave the build settings as they are and click **Deploy**.
3. Open your Netlify link. The **Today's Slate** tab loads `slate.json` by itself.

## 5. Optional extras
- **Phone alerts:** install the free **ntfy** app, subscribe to a long random topic name (30 random letters), then in the repo **Settings, Secrets and variables, Actions, New repository secret**: name `NTFY_TOPIC`, value is that same topic name.
- No odds API key to add, now or ever — the pipeline runs entirely on ESPN, Kalshi, Polymarket and our own collector network, all free and keyless. If a repo secret named `ODDS_API_KEY` is still sitting in **Settings, Secrets and variables, Actions** from an earlier setup, it's safe to delete; nothing reads it anymore.

## 6. Send me this
On your Netlify site open **Today's Slate** and copy the text under **Health check** and **Data sources used**. That shows which sources worked on real data, and it is what I need to fix anything that did not.
