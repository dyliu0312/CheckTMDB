# CheckTMDB

每日自动更新 TMDB、themoviedb、thetvdb 国内可正常连接 IP，解决 DNS 污染，供 tinyMediaManager、Kodi、群晖 VideoStation、Plex、Emby、Infuse、Nplayer 等正常刮削影片信息。

**本项目无需安装任何程序**，通过修改本地或路由器 hosts 文件即可使用。

## 使用方法

1. 安装 [SwitchHosts](https://github.com/oldj/SwitchHosts/releases/latest)
2. 添加远程 hosts：`https://raw.githubusercontent.com/dyliu0312/CheckTMDB/refs/heads/main/tmdb-hosts`
3. 设置自动刷新：`1 小时`

## 命令行参数

```bash
python host.py [选项]
```

**选项：**
| 参数 | 说明 |
|------|------|
| `-c, --categories CATEGORIES` | 指定分类，用逗号分隔（如 `tmdb,imdb,thetvdb`） |
| `-d, --domains {default,extended}` | 预设域名组合（默认：default） |
| `-G, --github` | 追加 GitHub hosts 到输出 |
| `-t, --timeout TIMEOUT` | 请求超时秒数（默认：30） |
| `-C, --config CONFIG` | 指定配置文件路径 |
| `--dry-run` | 仅显示配置，不发起请求 |

**域名分类：**
| 分类 | 说明 |
|------|------|
| `tmdb` | TMDB 电影/TV 元数据 |
| `imdb` | IMDB 电影数据库 |
| `thetvdb` | TVDB TV 刮削 |
| `fanart` | Fanart 艺术图 |
| `trakt` | Trakt 进度同步 |

**使用示例：**
```bash
# 默认模式（tmdb + imdb + thetvdb）
python host.py

# 查询特定分类（多个用逗号分隔）
python host.py -c tmdb
python host.py -c tmdb,imdb

# 使用所有分类
python host.py -d extended

# 追加 GitHub hosts
python host.py -G

# 自定义请求超时（秒）
python host.py -t 60

# 验证配置（不发起请求）
python host.py --dry-run
```

## 致谢

- 原作者：[cnwikee](https://github.com/cnwikee/CheckTMDB/)
- 参考：[521xueweihan](https://github.com/521xueweihan/GitHub520)
