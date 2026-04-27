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
    """Validate IP address (IPv4 or IPv6), excluding private/reserved IPs."""
    # IPv4 pattern
    ipv4_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
    # IPv6 pattern
    ipv6_pattern = r'^(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:){1,7}:|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:){1,5}(?::[0-9a-fA-F]{1,4}){1,2}|(?:[0-9a-fA-F]{1,4}:){1,4}(?::[0-9a-fA-F]{1,4}){1,3}|(?:[0-9a-fA-F]{1,4}:){1,3}(?::[0-9a-fA-F]{1,4}){1,4}|(?:[0-9a-fA-F]{1,4}:){1,2}(?::[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:(?:(?::[0-9a-fA-F]{1,4}){1,6})|:(?:(?::[0-9a-fA-F]{1,4}){1,7}|:)|fe80:(?::[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::(?:ffff(?::0{1,4}){0,1}:){0,1}(?:(?:25[0-5]|(?:2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(?:25[0-5]|(?:2[0-4]|1{0,1}[0-9]){0,1}[0-9])|(?:[0-9a-fA-F]{1,4}:){1,4}:(?:(?:25[0-5]|(?:2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(?:25[0-5]|(?:2[0-4]|1{0,1}[0-9]){0,1}[0-9]))$'
    
    if not (re.match(ipv4_pattern, ip) or re.match(ipv6_pattern, ip, re.IGNORECASE)):
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
    """Ping an IP address and return median latency of 3 attempts (in milliseconds)."""
    try:
        from ping3 import ping
        times = []
        for _ in range(3):
            result = ping(ip, timeout=timeout)
            if result is not None:
                times.append(result * 1000)  # Convert to ms
        
        if not times:
            return float('inf')
        
        # Return median (middle value after sorting)
        return sorted(times)[len(times) // 2]
    except Exception as e:
        logger.debug(f"Ping {ip} failed: {e}")
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
    """Lookup both IPv4 and IPv6 for a domain using Google DNS."""
    ipv4_ips = google_lookup(domain, "A", timeout)
    time.sleep(config['rate_limiting']['between_domains_delay'])
    ipv6_ips = google_lookup(domain, "AAAA", timeout)
    return domain, ipv4_ips, ipv6_ips


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


def write_file(ipv4_hosts_content: str, ipv6_hosts_content: str, update_time: str, github_append: bool = False, config: dict|None = None) -> bool:
    """Write hosts content to files."""
    output_doc_path = os.path.join(os.path.dirname(__file__), "README.md")
    template_path = os.path.join(os.path.dirname(__file__), "README_template.md")

    if not os.path.exists(output_doc_path):
        logger.error("README.md not found")
        return False

    with open(output_doc_path, "r", encoding='utf-8') as f:
        old_readme_md_content = f.read()

    if not old_readme_md_content:
        logger.error("README.md is empty")
        return False

    old_ipv4_block = old_readme_md_content.split("```bash")[1].split("```")[0].strip()
    old_ipv4_hosts = old_ipv4_block.split("# Update time:")[0].strip()
    old_ipv6_block = old_readme_md_content.split("```bash")[2].split("```")[0].strip()
    old_ipv6_hosts = old_ipv6_block.split("# Update time:")[0].strip()

    # Process IPv4
    if ipv4_hosts_content:
        new_ipv4_hosts = ipv4_hosts_content.split("# Update time:")[0].strip()
        if old_ipv4_hosts == new_ipv4_hosts:
            logger.info("IPv4 host not changed")
            w_ipv4_block = old_ipv4_block
        else:
            w_ipv4_block = ipv4_hosts_content
            write_host_file(ipv4_hosts_content, 'ipv4', github_append, config)
    else:
        w_ipv4_block = old_ipv4_block

    # Process IPv6
    if ipv6_hosts_content:
        new_ipv6_hosts = ipv6_hosts_content.split("# Update time:")[0].strip()
        if old_ipv6_hosts == new_ipv6_hosts:
            logger.info("IPv6 host not changed")
            w_ipv6_block = old_ipv6_block
        else:
            w_ipv6_block = ipv6_hosts_content
            write_host_file(ipv6_hosts_content, 'ipv6', github_append, config)
    else:
        w_ipv6_block = old_ipv6_block

    with open(template_path, "r", encoding='utf-8') as f:
        template_str = f.read()

    hosts_content = template_str.format(
        ipv4_hosts_str=w_ipv4_block,
        ipv6_hosts_str=w_ipv6_block,
        update_time=update_time
    )

    with open(output_doc_path, "w", encoding='utf-8') as f:
        f.write(hosts_content)

    return True


def write_host_file(hosts_content: str, filename: str, github_append: bool = False, config: dict|None = None) -> None:
    """Write hosts content to tmdb-hosts or tmdb-hosts-v6 file."""
    if filename == 'ipv4':
        output_file_path = os.path.join(os.path.dirname(__file__), "tmdb-hosts")
        log_name = "tmdb-hosts"
    else:
        output_file_path = os.path.join(os.path.dirname(__file__), "tmdb-hosts-v6")
        log_name = "tmdb-hosts-v6"

    if github_append and config is not None:
        logger.info("Appending GitHub hosts")
        github_hosts = get_github_hosts(config)
        if github_hosts:
            hosts_content = hosts_content + "\n" + github_hosts

    with open(output_file_path, "w", encoding='utf-8') as f:
        f.write(hosts_content)

    logger.info(f"Updated {log_name}")


def lookup_all_domains(domains: list, config: dict, timeout: int = 30) -> dict:
    """Look up all domains in parallel using Google DNS."""
    dns_workers = config['parallelism']['dns_workers']

    results = {}
    with ThreadPoolExecutor(max_workers=dns_workers) as executor:
        futures = {executor.submit(lookup_domain_google, domain, config, timeout): domain for domain in domains}
        for future in as_completed(futures):
            domain = futures[future]
            try:
                d, ipv4, ipv6 = future.result()
                results[d] = {'ipv4': ipv4, 'ipv6': ipv6}
                logger.info(f"Completed {d}: IPv4={len(ipv4)}, IPv6={len(ipv6)}")
            except Exception as e:
                logger.error(f"Failed to lookup {domain}: {e}")
                results[domain] = {'ipv4': [], 'ipv6': []}

    return results


def main():
    parser = argparse.ArgumentParser(description='Check TMDB domains and find fastest IPs')
    parser.add_argument('--config', type=str, default=None,
                        help='Path to config.json (default: ./config.json)')
    parser.add_argument('-G', '--github', action='store_true',
                        help='Append GitHub hosts to output')
    parser.add_argument('--domains', choices=['default', 'extended'], default='default',
                        help='Domain set to use (default: default)')
    parser.add_argument('--categories', type=str, default=None,
                        help='Comma-separated categories to use (e.g., tmdb,imdb,thetvdb)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show configuration without making requests')
    parser.add_argument('--timeout', type=int, default=30,
                        help='Request timeout in seconds (default: 30)')

    args = parser.parse_args()

    config = load_config(args.config)

    # Resolve domains from categories
    if args.categories:
        category_names = [c.strip() for c in args.categories.split(',')]
    else:
        category_names = config['domains'].get(args.domains, config['domains']['default'])

    # Build domain -> category mapping and expand category names to actual domain lists
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
        logger.info(f"[DRY RUN] Categories: {category_names}")
        logger.info(f"[DRY RUN] Domains ({len(domain_list)}): {domain_list}")
        logger.info(f"[DRY RUN] Parallelism: dns_workers={config['parallelism']['dns_workers']}, ping_workers={config['parallelism']['ping_workers']}")
        logger.info("[DRY RUN] Dry run complete, no requests made")
        return

    logger.info("Starting TMDB domain check (Google DNS mode)")
    logger.info(f"Processing {len(domain_list)} domains from categories: {category_names}")

    # Lookup all domains in parallel (Google DNS mode)
    lookup_results = lookup_all_domains(domain_list, config, args.timeout)

    ipv4_results = []
    ipv6_results = []

    ping_workers = config['parallelism']['ping_workers']
    between_ips_delay = config['rate_limiting']['between_ips_delay']

    for domain, ips in lookup_results.items():
        ipv4_ips = ips['ipv4']
        ipv6_ips = ips['ipv6']

        if not ipv4_ips and not ipv6_ips:
            logger.warning(f"No IPs found for {domain}, skipping")
            continue

        if ipv4_ips:
            fastest_ipv4 = find_fastest_ip(ipv4_ips, ping_workers, between_ips_delay)
            if fastest_ipv4:
                ipv4_results.append((fastest_ipv4, domain))
                logger.info(f"Domain {domain} fastest IPv4: {fastest_ipv4}")

        if ipv6_ips:
            fastest_ipv6 = find_fastest_ip(ipv6_ips, ping_workers, between_ips_delay)
            if fastest_ipv6:
                ipv6_results.append((fastest_ipv6, domain))
                logger.info(f"Domain {domain} fastest IPv6: {fastest_ipv6}")

        time.sleep(config['rate_limiting']['between_domains_delay'])

    if not ipv4_results and not ipv6_results:
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

    ipv6_hosts_content = TMDB_HOST_TEMPLATE.format(
        content=build_grouped_content(ipv6_results, 50),
        update_time=update_time
    ) if ipv6_results else ""

    write_file(ipv4_hosts_content, ipv6_hosts_content, update_time, args.github, config)

    logger.info("Done!")


if __name__ == "__main__":
    main()
