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
    """Validate IP address (IPv4 or IPv6)."""
    ipv4_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
    ipv6_pattern = r'^(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:){1,7}:|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:){1,5}(?::[0-9a-fA-F]{1,4}){1,2}|(?:[0-9a-fA-F]{1,4}:){1,4}(?::[0-9a-fA-F]{1,4}){1,3}|(?:[0-9a-fA-F]{1,4}:){1,3}(?::[0-9a-fA-F]{1,4}){1,4}|(?:[0-9a-fA-F]{1,4}:){1,2}(?::[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:(?:(?::[0-9a-fA-F]{1,4}){1,6})|:(?:(?::[0-9a-fA-F]{1,4}){1,7}|:)|fe80:(?::[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::(?:ffff(?::0{1,4}){0,1}:){0,1}(?:(?:25[0-5]|(?:2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(?:25[0-5]|(?:2[0-4]|1{0,1}[0-9]){0,1}[0-9])|(?:[0-9a-fA-F]{1,4}:){1,4}:(?:(?:25[0-5]|(?:2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(?:25[0-5]|(?:2[0-4]|1{0,1}[0-9]){0,1}[0-9]))$'
    return bool(re.match(ipv4_pattern, ip) or re.match(ipv6_pattern, ip, re.IGNORECASE))


def ping_ip(ip: str, port: int = 80, timeout: float = 2.0) -> float:
    """Ping an IP address and return latency in milliseconds."""
    try:
        start_time = time.time()
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            latency = (time.time() - start_time) * 1000
            return latency
    except Exception as e:
        logger.debug(f"Ping {ip} failed: {e}")
        return float('inf')


def find_fastest_ip(ips: list, ping_workers: int = 10, between_ips_delay: float = 0.5) -> Optional[str]:
    """Find the fastest IP from a list using parallel ping tests."""
    if not ips:
        return None

    valid_ips = [ip.strip() for ip in ips if ip.strip()]
    if not valid_ips:
        return None

    ip_latencies = []

    with ThreadPoolExecutor(max_workers=ping_workers) as executor:
        futures = {executor.submit(ping_ip, ip): ip for ip in valid_ips}
        for future in as_completed(futures):
            ip = futures[future]
            latency = future.result()
            ip_latencies.append((ip, latency))
            time.sleep(between_ips_delay)

    if not ip_latencies:
        return None

    fastest = min(ip_latencies, key=lambda x: x[1])
    logger.info(f"Fastest IP: {fastest[0]} ({fastest[1]:.1f}ms)")

    for ip, latency in sorted(ip_latencies, key=lambda x: x[1]):
        logger.debug(f"IP: {ip} - Latency: {latency:.1f}ms")

    return fastest[0]


# DNS Checker (dnschecker.org) mode functions
@retry_with_backoff(max_tries=3, base_delay=1.0)
def get_csrf_token(udp: float, config: dict) -> Optional[str]:
    """Get CSRF token from dnschecker.org."""
    csrf_url = config['apis']['dnschecker']['csrf_url']
    country_code = config['country_code']
    headers = {
        'referer': f'https://dnschecker.org/country/{country_code}/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    response = requests.get(f"{csrf_url}?udp={udp}", headers=headers)
    if response.status_code == 200:
        return response.json().get('csrf')
    return None


@retry_with_backoff(max_tries=3, base_delay=1.0)
def dnschecker_lookup(domain: str, csrf_token: str, udp: float, record_type: str, config: dict) -> list:
    """Lookup domain IPs using dnschecker.org API."""
    api_url = config['apis']['dnschecker']['api_url']
    country_code = config['country_code']
    argument = "A" if record_type == "A" else "AAAA"

    url = f"{api_url}/{argument}/{domain}?dns_key=country&dns_value={country_code}&v=0.36&cd_flag=1&upd={udp}"
    headers = {
        'csrftoken': csrf_token,
        'referer': f'https://dnschecker.org/country/{country_code}/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        if 'result' in data and 'ips' in data['result']:
            ips_str = data['result']['ips']
            if '<br />' in ips_str:
                return [ip.strip() for ip in ips_str.split('<br />') if ip.strip()]
            elif ips_str.strip():
                return [ips_str.strip()]
    return []


def lookup_domain_dnschecker(domain: str, config: dict, csrf_token: str = None, udp: float = None) -> tuple:
    """Lookup both IPv4 and IPv6 for a domain using dnschecker.org."""
    logger.info(f"Looking up {domain} via dnschecker.org")

    if not csrf_token or not udp:
        udp = random.random() * 1000 + (int(time.time() * 1000) % 1000)
        csrf_token = get_csrf_token(udp, config)
        if not csrf_token:
            logger.error(f"Failed to get CSRF token for {domain}")
            return domain, [], []

    ipv4_ips = dnschecker_lookup(domain, csrf_token, udp, "A", config)
    ipv6_ips = dnschecker_lookup(domain, csrf_token, udp, "AAAA", config)

    return domain, ipv4_ips, ipv6_ips


# Google DNS mode functions
@retry_with_backoff(max_tries=3, base_delay=1.0)
def google_lookup(domain: str, record_type: str) -> list:
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
        response = requests.get(url, headers=headers, params=params, timeout=10)
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


def lookup_domain_google(domain: str, config: dict) -> tuple:
    """Lookup both IPv4 and IPv6 for a domain using Google DNS."""
    ipv4_ips = google_lookup(domain, "A")
    time.sleep(config['rate_limiting']['between_domains_delay'])
    ipv6_ips = google_lookup(domain, "AAAA")
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


def write_file(ipv4_hosts_content: str, ipv6_hosts_content: str, update_time: str, github_append: bool = False, config: dict = None) -> bool:
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


def write_host_file(hosts_content: str, filename: str, github_append: bool = False, config: dict = None) -> None:
    """Write hosts content to Tmdb_host_ipv4/ipv6 file."""
    output_file_path = os.path.join(os.path.dirname(__file__), f"Tmdb_host_{filename}")

    if github_append:
        logger.info("Appending GitHub hosts")
        github_hosts = get_github_hosts(config) if config else None
        if github_hosts:
            hosts_content = hosts_content + "\n" + github_hosts

    with open(output_file_path, "w", encoding='utf-8') as f:
        f.write(hosts_content)

    logger.info(f"Updated Tmdb_host_{filename}")


def lookup_all_domains(domains: list, mode: str, config: dict, csrf_token: str = None, udp: float = None) -> dict:
    """Look up all domains in parallel."""
    dns_workers = config['parallelism']['dns_workers']

    lookup_func = lookup_domain_dnschecker if mode == 'dnschecker' else lookup_domain_google

    results = {}
    with ThreadPoolExecutor(max_workers=dns_workers) as executor:
        futures = {executor.submit(lookup_func, domain, config, csrf_token, udp): domain for domain in domains}
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
    parser.add_argument('--mode', choices=['dnschecker', 'google'], default='dnschecker',
                        help='DNS lookup mode (default: dnschecker)')
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
        logger.info(f"[DRY RUN] Mode: {args.mode}")
        logger.info(f"[DRY RUN] Categories: {category_names}")
        logger.info(f"[DRY RUN] Domains ({len(domain_list)}): {domain_list}")
        logger.info(f"[DRY RUN] Country code: {config['country_code']}")
        logger.info(f"[DRY RUN] Parallelism: dns_workers={config['parallelism']['dns_workers']}, ping_workers={config['parallelism']['ping_workers']}")
        logger.info("[DRY RUN] Dry run complete, no requests made")
        return

    logger.info(f"Starting TMDB domain check in {args.mode} mode")
    logger.info(f"Processing {len(domain_list)} domains from categories: {category_names}")

    # Pre-fetch CSRF token and UDP for dnschecker mode
    csrf_token = None
    udp = None
    if args.mode == 'dnschecker':
        udp = random.random() * 1000 + (int(time.time() * 1000) % 1000)
        csrf_token = get_csrf_token(udp, config)
        if not csrf_token:
            logger.error("Failed to get CSRF token, exiting")
            sys.exit(1)
        logger.info("CSRF token obtained, will reuse for all domains")

    # Lookup all domains in parallel
    lookup_results = lookup_all_domains(domain_list, args.mode, config, csrf_token, udp)

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
