# CheckTMDB

每日自动更新 TMDB、themoviedb、thetvdb 国内可正常连接 IP，解决 DNS 污染，供 tinyMediaManager、Kodi、群晖 VideoStation、Plex、Emby、Infuse、Nplayer 等正常刮削影片信息。

**本项目无需安装任何程序**，通过修改本地或路由器 hosts 文件即可使用。

## 文件地址

- TMDB IPv4 hosts：[Tmdb_host_ipv4](https://raw.githubusercontent.com/dyliu0312/CheckTMDB/refs/heads/main/Tmdb_host_ipv4)
- TMDB IPv6 hosts：[Tmdb_host_ipv6](https://raw.githubusercontent.com/dyliu0312/CheckTMDB/refs/heads/main/Tmdb_host_ipv6)

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
   - IPv4：`https://raw.githubusercontent.com/dyliu0312/CheckTMDB/refs/heads/main/Tmdb_host_ipv4`
   - IPv6：`https://raw.githubusercontent.com/dyliu0312/CheckTMDB/refs/heads/main/Tmdb_host_ipv6`
3. 设置自动刷新：`1 小时`

## 命令行参数

```bash
python check_tmdb.py [选项]
```

**选项：**
| 参数 | 说明 |
|------|------|
| `--mode {dnschecker,google}` | DNS 查询模式（默认：dnschecker） |
| `--categories CATEGORIES` | 指定分类，用逗号分隔（如 `tmdb,imdb,thetvdb`） |
| `--domains {default,extended}` | 预设域名组合（默认：default） |
| `-G, --github` | 追加 GitHub hosts 到输出 |
| `--dry-run` | 仅显示配置，不发起请求 |
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
python check_tmdb.py

# 使用所有分类
python check_tmdb.py --domains=extended

# 仅查询 tmdb 和 thetvdb
python check_tmdb.py --categories=tmdb,thetvdb

# 使用 Google DNS 模式
python check_tmdb.py --mode=google

# 追加 GitHub hosts
python check_tmdb.py -G

# 验证配置（不发起请求）
python check_tmdb.py --dry-run
```

## 致谢

- 上游项目：[cnwikee/CheckTMDB](https://github.com/cnwikee/CheckTMDB/)
