import argparse
import json
import logging
import os
import random
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Optional

import requests

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = None) -> dict:
    """Load configuration from JSON file."""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def retry_with_backoff(max_tries: int = 3, base_delay: float = 1.0,
                       max_delay: float = 30.0, exponential_base: float = 2,
                       jitter: bool = True):
    """Decorator for retry with exponential backoff and optional jitter."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_tries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_tries - 1:
                        raise
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    if jitter:
                        delay *= (0.5 + random.random())
                    logger.warning(f"{func.__name__} attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


TMDB_HOST_TEMPLATE = """# Tmdb Hosts Start
{content}
# Update time: {update_time}
# Tmdb Hosts End
"""


def validate_ip(ip: str) -> bool:
    """Validate IPv4 address, excluding private/reserved IPs."""
    ipv4_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'

    if not re.match(ipv4_pattern, ip):
        return False

    # Filter out private/reserved IPv4
    if ip.startswith(('10.', '172.16.', '172.17.', '172.18.', '172.19.',
                     '172.20.', '172.21.', '172.22.', '172.23.', '172.24.',
                     '172.25.', '172.26.', '172.27.', '172.28.', '172.29.',
                     '172.30.', '172.31.', '192.168.', '127.', '0.', '169.254.',
                     '255.', '224.', '240.')):
        return False

    return True


def ping_ip(ip: str, timeout: float = 2.0) -> float:
    """Test TCP connection latency to IP port 80, return median of 3 attempts (in ms)."""
    import socket
    try:
        times = []
        for _ in range(3):
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            try:
                sock.connect((ip, 80))
                sock.close()
                times.append((time.time() - start) * 1000)
            except (socket.timeout, socket.error):
                pass
            finally:
                sock.close()

        if not times:
            return float('inf')

        return sorted(times)[len(times) // 2]
    except Exception as e:
        logger.debug(f"TCP connect {ip} failed: {e}")
        return float('inf')


def find_fastest_ip(ips: list, ping_workers: int = 10, between_ips_delay: float = 0.5) -> Optional[str]:
    """Find the fastest IP from a list using parallel ping tests."""
    if not ips:
        return None

    valid_ips = [ip.strip() for ip in ips if ip.strip() and validate_ip(ip)]
    if not valid_ips:
        return None

    ip_latencies = []

    with ThreadPoolExecutor(max_workers=ping_workers) as executor:
        futures = {executor.submit(ping_ip, ip): ip for ip in valid_ips}
        for future in as_completed(futures):
            ip = futures[future]
            latency = future.result()
            if latency < float('inf'):
                ip_latencies.append((ip, latency))
            time.sleep(between_ips_delay)

    if not ip_latencies:
        return None

    fastest = min(ip_latencies, key=lambda x: x[1])
    logger.info(f"Fastest IP: {fastest[0]} ({fastest[1]:.1f}ms)")

    for ip, latency in sorted(ip_latencies, key=lambda x: x[1]):
        logger.debug(f"IP: {ip} - Latency: {latency:.1f}ms")

    return fastest[0]


# Google DNS mode functions
@retry_with_backoff(max_tries=3, base_delay=1.0)
def google_lookup(domain: str, record_type: str, timeout: int = 30) -> list:
    """Lookup domain IPs using Google DNS API."""
    logger.info(f"Looking up {domain} via Google DNS ({record_type})")

    url = 'https://dns.google/resolve'
    headers = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "content-type": "application/json; charset=UTF-8",
        "referer": f"https://dns.google/query?name={domain}&rr_type={record_type}&ecs=",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"
    }
    params = {'name': domain, 'type': record_type}

    all_ips = []
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            logger.warning(f"Invalid response format for {domain}")
            return all_ips

        answer_list = data.get("Answer", [])
        for answer in answer_list:
            ip = answer.get("data")
            if ip and validate_ip(ip):
                all_ips.append(ip)
                logger.debug(f"Found IP: {ip}")

    except Exception as e:
        logger.error(f"Google DNS lookup failed for {domain}: {e}")

    return all_ips


def lookup_domain_google(domain: str, config: dict, timeout: int = 30) -> tuple:
    """Lookup IPv4 for a domain using Google DNS."""
    ipv4_ips = google_lookup(domain, "A", timeout)
    return domain, ipv4_ips


def get_github_hosts(config: dict) -> Optional[str]:
    """Fetch GitHub hosts from alternative sources."""
    github_hosts_urls = config['apis']['github_hosts']

    for url in github_hosts_urls:
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                logger.info(f"Successfully fetched GitHub hosts from {url}")
                return response.text
            else:
                logger.warning(f"Failed to fetch from {url}: HTTP {response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching from {url}: {e}")

    logger.error("All GitHub hosts sources failed")
    return None


def write_file(ipv4_hosts_content: str, github_append: bool = False, config: dict|None = None) -> bool:
    """Write hosts content to tmdb-hosts file."""
    write_host_file(ipv4_hosts_content, github_append, config)
    return True


def write_host_file(hosts_content: str, github_append: bool = False, config: dict|None = None) -> None:
    """Write hosts content to tmdb-hosts file."""
    output_file_path = os.path.join(os.path.dirname(__file__), "tmdb-hosts")

    if github_append and config is not None:
        logger.info("Appending GitHub hosts")
        github_hosts = get_github_hosts(config)
        if github_hosts:
            hosts_content = hosts_content + "\n" + github_hosts

    with open(output_file_path, "w", encoding='utf-8') as f:
        f.write(hosts_content)

    logger.info("Updated tmdb-hosts")


def lookup_all_domains(domains: list, config: dict, timeout: int = 30) -> dict:
    """Look up all domains in parallel using Google DNS."""
    dns_workers = config['parallelism']['dns_workers']

    results = {}
    with ThreadPoolExecutor(max_workers=dns_workers) as executor:
        futures = {executor.submit(lookup_domain_google, domain, config, timeout): domain for domain in domains}
        for future in as_completed(futures):
            domain = futures[future]
            try:
                d, ipv4 = future.result()
                results[d] = {'ipv4': ipv4}
                logger.info(f"Completed {d}: IPv4={len(ipv4)}")
            except Exception as e:
                logger.error(f"Failed to lookup {domain}: {e}")
                results[domain] = {'ipv4': []}

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Check TMDB domains and find fastest IPs via Google DNS',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python host.py                     Run with default categories (tmdb,imdb,thetvdb)
  python host.py -c tmdb             Query only tmdb category
  python host.py -c tmdb,imdb        Query tmdb and imdb categories
  python host.py -s extended         Use all categories
  python host.py -d api.tmdb.org     Query a specific domain
  python host.py -d api.tmdb.org -d tmdb.org   Query multiple specific domains
  python host.py -G                  Append GitHub hosts to output
  python host.py -t 60               Set request timeout to 60 seconds
  python host.py --dry-run           Show configuration without making requests
        """
    )
    parser.add_argument('-c', '--categories', type=str, default=None,
                        help='Comma-separated categories to query (e.g., tmdb,imdb,thetvdb)')
    parser.add_argument('-s', '--domain-set', choices=['default', 'extended'], default='default',
                        help='Preset domain groups: default=(tmdb,imdb,thetvdb), extended=all (default: default)')
    parser.add_argument('-d', '--domain', type=str, action='append', default=None,
                        help='Specify a single domain to query (can be used multiple times)')
    parser.add_argument('-G', '--github', action='store_true',
                        help='Append GitHub hosts to output')
    parser.add_argument('-t', '--timeout', type=int, default=30,
                        help='Request timeout in seconds (default: 30)')
    parser.add_argument('-C', '--config', type=str, default=None,
                        help='Path to config.json (default: ./config.json)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show configuration without making requests')

    args = parser.parse_args()

    config = load_config(args.config)

    # Resolve domain list: --domain takes highest priority, then --categories, then --domain-set
    if args.domain:
        domain_list = args.domain
        domain_to_category = {d: "other" for d in domain_list}
    elif args.categories:
        category_names = [c.strip() for c in args.categories.split(',')]
        domain_to_category = {}
        domain_list = []
        for name in category_names:
            if name in config['domains']['categories']:
                for d in config['domains']['categories'][name]:
                    if d not in domain_to_category:
                        domain_to_category[d] = name
                        domain_list.append(d)
            else:
                if name not in domain_to_category:
                    domain_to_category[name] = "other"
                    domain_list.append(name)
    else:
        category_names = config['domains'].get(args.domain_set, config['domains']['default'])
        domain_to_category = {}
        domain_list = []
        for name in category_names:
            if name in config['domains']['categories']:
                for d in config['domains']['categories'][name]:
                    if d not in domain_to_category:
                        domain_to_category[d] = name
                        domain_list.append(d)
            else:
                if name not in domain_to_category:
                    domain_to_category[name] = "other"
                    domain_list.append(name)

    if args.dry_run:
        logger.info(f"[DRY RUN] Timeout: {args.timeout}s")
        if args.domain:
            logger.info(f"[DRY RUN] Mode: specific domains")
        elif args.categories:
            logger.info(f"[DRY RUN] Mode: categories ({args.categories})")
        else:
            logger.info(f"[DRY RUN] Mode: domain-set ({args.domain_set})")
        logger.info(f"[DRY RUN] Domains ({len(domain_list)}): {domain_list}")
        logger.info(f"[DRY RUN] Parallelism: dns_workers={config['parallelism']['dns_workers']}, ping_workers={config['parallelism']['ping_workers']}")
        logger.info("[DRY RUN] Dry run complete, no requests made")
        return

    logger.info("Starting TMDB domain check (Google DNS mode)")
    if args.domain:
        logger.info(f"Mode: specific domains, {len(domain_list)} domains: {domain_list}")
    elif args.categories:
        logger.info(f"Mode: categories ({args.categories}), {len(domain_list)} domains: {domain_list}")
    else:
        logger.info(f"Mode: domain-set ({args.domain_set}), {len(domain_list)} domains: {domain_list}")

    # Lookup all domains in parallel (Google DNS mode)
    lookup_results = lookup_all_domains(domain_list, config, args.timeout)

    ipv4_results = []
    failed_domains = []

    ping_workers = config['parallelism']['ping_workers']
    between_ips_delay = config['rate_limiting']['between_ips_delay']

    for domain, ips in lookup_results.items():
        ipv4_ips = ips['ipv4']

        if not ipv4_ips:
            logger.warning(f"No IPs found for {domain}, skipping")
            failed_domains.append(domain)
            continue

        fastest_ipv4 = find_fastest_ip(ipv4_ips, ping_workers, between_ips_delay)
        if fastest_ipv4:
            ipv4_results.append((fastest_ipv4, domain))
            logger.info(f"Domain {domain} fastest IPv4: {fastest_ipv4}")
        else:
            logger.warning(f"All ping failed for {domain}, skipping")
            failed_domains.append(domain)

        time.sleep(config['rate_limiting']['between_domains_delay'])

    if not ipv4_results:
        logger.error("No results obtained, exiting")
        sys.exit(1)

    update_time = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0).isoformat()

    # Group results by category
    def build_grouped_content(results, ip_width):
        lines = []
        current_category = None
        for ip, domain in results:
            cat = domain_to_category.get(domain, "other")
            if cat != current_category:
                if current_category is not None:
                    lines.append("")
                lines.append(f"# === {cat.upper()} ===")
                current_category = cat
            lines.append(f"{ip:<{ip_width}} {domain}")
        return "\n".join(lines)

    ipv4_hosts_content = TMDB_HOST_TEMPLATE.format(
        content=build_grouped_content(ipv4_results, 27),
        update_time=update_time
    ) if ipv4_results else ""

    write_file(ipv4_hosts_content, args.github, config)

    logger.info(f"Done! {len(ipv4_results)} succeeded, {len(failed_domains)} failed" +
                (f" ({', '.join(failed_domains)})" if failed_domains else ""))


if __name__ == "__main__":
    main()