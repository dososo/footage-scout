# 交接说明:自动渠道没有时,请用户自己下载

适用于 Pexels、Pixabay、Mixkit、NARA 等不允许自动访问或会拦截程序的网站。

1. 把 `handoff`(或项目里的 `LINKS.md`)中对应镜头的链接给用户。`kind=home` 的只有首页,要用户自己搜。
2. 对用户说:「请在浏览器里打开链接,看清许可再下载。把文件放进 `inbox/<镜头编号>/`。」
3. 用户放好后,MCP 调 `register_download(project)`,其他参数都不填;命令行用 `fsc inbox footage/shotlist.json --json`。
4. 看结果:
   - `registered`:已登记。多数是 HOLD,因为单条素材的许可没有核实过。**登记不等于能发布。**
   - `unpaired` 写「no known source page recorded」:请用户在视频旁边放一个同名文本文件(如 `a.mp4.txt`),里面只写素材页网址,再来一次。
   - `unpaired` 写「shot unclear」:请用户把文件挪进 `inbox/<镜头编号>/`。
   - 写「page host is not a known source」:这个网站不在名单里,不登记。
5. 一次登记一个、文件在下载目录时:`register_download(project, shot_id, page_url, file)`,三个都要填。

不要替用户打开需要登录、付费或有人机验证的页面。不要用浏览器自动化批量下载这些站点。
