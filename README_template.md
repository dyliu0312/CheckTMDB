# CheckTMDB

每日自动更新 TMDB、themoviedb、thetvdb 国内可正常连接 IP，解决 DNS 污染，供 tinyMediaManager、Kodi、群晖 VideoStation、Plex、Emby、Infuse、Nplayer 等正常刮削影片信息。

**本项目无需安装任何程序**，通过修改本地或路由器 hosts 文件即可使用。

## 文件地址

- TMDB IPv4 hosts：[tmdb-hosts](https://raw.githubusercontent.com/dyliu0312/CheckTMDB/refs/heads/main/tmdb-hosts)
- TMDB IPv6 hosts：[tmdb-hosts-v6](https://raw.githubusercontent.com/dyliu0312/CheckTMDB/refs/heads/main/tmdb-hosts-v6)

## 使用方法

### 手动方式

#### 1. 复制 hosts 内容

**IPv4：**
```bash
{ipv4_hosts_str}
```

**IPv6：**
```bash
{ipv6_hosts_str}
```

> [!NOTE]
> 由于项目运行在 GitHub Actions 网络环境，请自行测试可用性。

#### 2. 修改 hosts 文件

hosts 文件位置：
- Windows：`C:\Windows\System32\drivers\etc\hosts`
- Linux/Mac：`/etc/hosts`
- Android：`/system/etc/hosts`

#### 3. 刷新 DNS

- Windows：`ipconfig /flushdns`
- Linux：`sudo nscd restart` 或 `sudo /etc/init.d/nscd restart`
- Mac：`sudo killall -HUP mDNSResponder`

### 自动方式（SwitchHosts）

1. 安装 [SwitchHosts](https://github.com/oldj/SwitchHosts/releases/latest)
2. 添加远程 hosts：
   - IPv4：`https://raw.githubusercontent.com/dyliu0312/CheckTMDB/refs/heads/main/tmdb-hosts`
   - IPv6：`https://raw.githubusercontent.com/dyliu0312/CheckTMDB/refs/heads/main/tmdb-hosts-v6`
3. 设置自动刷新：`1 小时`

## 命令行参数

```bash
python host.py [选项]
```

**选项：**
| 参数 | 说明 |
|------|------|
| `--categories CATEGORIES` | 指定分类，用逗号分隔（如 `tmdb,imdb,thetvdb`） |
| `--domains {default,extended}` | 预设域名组合（默认：default） |
| `-G, --github` | 追加 GitHub hosts 到输出 |
| `--dry-run` | 仅显示配置，不发起请求 |
| `--timeout TIMEOUT` | 请求超时秒数（默认：30） |
| `--config CONFIG` | 指定配置文件路径 |

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

# 使用所有分类
python host.py --domains=extended

# 仅查询 tmdb 和 thetvdb
python host.py --categories=tmdb,thetvdb

# 追加 GitHub hosts
python host.py -G

# 验证配置（不发起请求）
python host.py --dry-run
```

## 致谢

- 上游项目：[cnwikee/CheckTMDB](https://github.com/cnwikee/CheckTMDB/)
- DNS 查询及 Ping 优化参考：[GitHub520](https://github.com/521xueweihan/GitHub520)
