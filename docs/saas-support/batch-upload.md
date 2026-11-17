# 文档批量上传

侧栏文档分组右侧的上传按钮会打开批量上传窗口。先选择多个文件，核对清单后点击“开始上传”。收起侧栏时也可以从上传图标打开窗口。

## 默认限制

| 范围 | 上限 | 后端配置 |
| --- | --- | --- |
| 每批数量 | 10 个 | `MAX_UPLOAD_BATCH_FILES` |
| 单文件大小 | 50 MB | `MAX_UPLOAD_SIZE_MB` |
| 每批文件合计大小 | 100 MB | `MAX_UPLOAD_BATCH_SIZE_MB` |

大小按 `1 MB = 1024 × 1024 字节` 计算，恰好达到限制时允许上传。前端通过 `GET /api/v1/upload/limits` 获取实际限制，不依赖硬编码默认值。数量或大小超限时，`POST /api/v1/upload/batch` 在写入前拒绝整批；后端检查实际读取的字节数。

批内文件按顺序处理，逐文件返回结果。一个文件类型不支持或解析失败时，其余文件继续处理。解析失败的文件已保存并会显示“文档已上传，但解析失败”；不要将它误认为从未上传。发生连接中断时，先关闭窗口、刷新文档列表确认哪些文件已保存，再选择剩余文件上传，避免重复创建。

支持保存 PDF、TXT、MD、DOCX、CSV、JSON、XML；当前自动解析、正文预览与问答检索仅支持 PDF、TXT、MD。文件属于当前登录用户，不会自动变为公共语料。

## 部署

1. 前后端需一起更新，不需要数据库迁移。默认限制无需增加环境变量；需要调整时，在服务器 `.env` 设置上表三个配置并重新创建 backend 容器。
2. Next.js 代理已配置 110 MB 的请求体缓冲和 15 分钟等待。生产 nginx 配置模板也已调整，但发布应用镜像不会自动更新宿主机 nginx。
3. 在 ECS 的实际站点配置（当前为 `/etc/nginx/conf.d/rag.conf`）核对以下值，保留已有域名、证书和其他设置：

   ```nginx
   # server 块内，略大于 100 MB 总文件限制，为 multipart 边界留空间
   client_max_body_size 110m;

   # location / 块内
   proxy_read_timeout 900s;
   proxy_send_timeout 900s;
   ```

4. 修改后检查并重新加载：

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

若提高后端业务上限，需同步调整 `web/next.config.ts` 的 `proxyClientMaxBodySize`（需重建 web 镜像）和 nginx 请求体上限，并为 multipart 边界留余量。

## 验证

使用已登录账号选择 2 个小 TXT 或 MD，确认成功后文档列表出现文件；加入一个无效 PDF，确认其失败不影响其他文件。选择超过数量或大小限制的文件时，应在提交前显示具体错误。后端回归覆盖配置读取、精确大小边界、整批超限不写入、部分失败、用户归属与未登录拒绝。
