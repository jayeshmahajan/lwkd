import json
import re
import sys
import subprocess
import builtins
from datetime import datetime, timedelta

_print_buffer = []

def print(*args, **kwargs):
    sep = kwargs.get('sep', ' ')
    end = kwargs.get('end', '\n')
    file = kwargs.get('file', sys.stdout)

    if file in (sys.stdout, sys.stderr, None):
        msg = sep.join(str(arg) for arg in args) + end
        _print_buffer.append(msg)

    builtins.print(*args, **kwargs)

def get_last_week_range():
    today = datetime.now().date()
    # today.weekday() returns 0 for Monday, 6 for Sunday
    days_since_monday = today.weekday()
    monday_this_week = today - timedelta(days=days_since_monday)

    last_sunday = monday_this_week - timedelta(days=1)
    last_monday = last_sunday - timedelta(days=6)

    return last_monday.strftime('%Y-%m-%d'), last_sunday.strftime('%Y-%m-%d')

def get_prs(repo, start_date, end_date, limit=200):
    search_query = f"merged:{start_date}..{end_date}"
    cmd = [
        "gh", "pr", "list",
        "--repo", repo,
        "--state", "merged",
        "--search", search_query,
        "--limit", str(limit),
        "--json", "title,url,body,number,labels,author"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error fetching PRs: {result.stderr}")
        return []
    return json.loads(result.stdout)

def extract_release_note(body):
    if not body:
        return None
    match = re.search(r'```release-note\s*(.*?)\s*```', body, re.DOTALL | re.IGNORECASE)
    if match:
        note = match.group(1).strip()
        if note.upper() == "NONE" or not note:
            return None
        return note
    return None

def extract_kep_link(body):
    if not body:
        return None
    # Patterns for KEP links
    patterns = [
        r'https://github\.com/kubernetes/enhancements/issues/(\d+)',
        r'https://kep\.k8s\.io/(\d+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            if 'kep.k8s.io' in pattern:
                return f"https://kep.k8s.io/{match.group(1)}"
            return f"https://github.com/kubernetes/enhancements/issues/{match.group(1)}"
    return None

def is_deprecated(pr):
    # Only if the specific words are mentioned in title or release note
    note = extract_release_note(pr['body'])
    text = (pr['title'] + " " + (note if note else "")).lower()
    return 'deprecated' in text or 'deprecation' in text

def strip_html_comments(text):
    if not text:
        return ""
    # Remove HTML comments (including multi-line ones)
    return re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL).strip()

def format_line(text, url, author=None, kep_url=None):
    text = text.strip().rstrip('.')
    words = text.split()
    if len(words) > 4:
        prefix_len = min(2, len(words) - 2)
        prefix = " ".join(words[:prefix_len])
        link_words = words[prefix_len : prefix_len + 7]
        link_text = " ".join(link_words)
        suffix = " ".join(words[prefix_len + 7:])
        line = f"* {prefix} [{link_text}]({url}) {suffix}."
    else:
        line = f"* [{text}]({url})."

    if kep_url:
        line = line.rstrip('.') + f" ([KEP]({kep_url}))."

    if author:
        line += f" By @{author}."

    return line.strip().replace("  ", " ")

def main():
    start_date, end_date = get_last_week_range()
    # Default to a temp file if no argument provided
    output_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kubernetes_prs_last_week.md"
    repo = "kubernetes/kubernetes"

    print(f"Calculated date range for last week (Monday to Sunday):")
    print(f"Start: {start_date}")
    print(f"End:   {end_date}")

    while True:
        confirm = input("Proceed with fetching PRs? (yes/no): ").strip().lower()
        if confirm in ['yes', 'y']:
            break
        elif confirm in ['no', 'n']:
            while True:
                new_start = input("Enter new Start date (YYYY-MM-DD): ").strip()
                try:
                    datetime.strptime(new_start, '%Y-%m-%d')
                    start_date = new_start
                    break
                except ValueError:
                    print("Invalid date format. Please use YYYY-MM-DD.")
            while True:
                new_end = input("Enter new End date (YYYY-MM-DD): ").strip()
                try:
                    datetime.strptime(new_end, '%Y-%m-%d')
                    end_date = new_end
                    break
                except ValueError:
                    print("Invalid date format. Please use YYYY-MM-DD.")
            print(f"\nUpdated date range:")
            print(f"Start: {start_date}")
            print(f"End:   {end_date}")
        else:
            print("Aborting.")
            return

    print(f"Fetching PRs from {repo}...")
    prs = get_prs(repo, start_date, end_date)
    if not prs:
        print("No PRs found or error occurred.")
        return

    deprecated_prs = []
    other_prs = []

    for pr in prs:
        author = pr.get('author', {}).get('login', 'unknown')
        kep_url = extract_kep_link(pr['body'])

        # Fulfill "print author of the PR and read content"
        print(f"\n--- {pr['url']} by https://github.com/{author} ---")
        print(f"Title: {pr['title']}")
        if pr['body']:
            # Show first few lines as "reading content" (stripping HTML comments)
            content = strip_html_comments(pr['body'])
            snippet = content[:3000].replace('\r\n', '\n')
            print(f"Content Snippet:\n{snippet}{'...' if len(content) > 3000 else ''}")

        if is_deprecated(pr):
            deprecated_prs.append((pr, author, kep_url))
        else:
            other_prs.append((pr, author, kep_url))

    with open(output_file, 'w') as f:
        # Format end_date for the title (e.g., June 7, 2026)
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        formatted_end_date = end_dt.strftime('%B %-d, %Y')
        f.write(f"# Week Ending {formatted_end_date}: Featured PRs\n\n")

        all_prs_url = f"https://github.com/kubernetes/kubernetes/pulls?q=is%3Apr+merged%3A{start_date}..{end_date}"
        important_prs_url = f"https://github.com/kubernetes/kubernetes/pulls?q=is%3Apr+merged%3A{start_date}..{end_date}+label%3Arelease-note%2Clabel%3Arelease-note-action-required%2C%22kind%2Fdeprecation%22%2C%22kind%2Fapi-change%22%2C%22kind%2Ffeature%22%2C%22size%2Fl%22"

        f.write(f"**All PRs:** {all_prs_url}\n\n")
        f.write(f"**Important PRs:** {important_prs_url}\n\n")

        if other_prs:
            f.write("## General Updates\n")
            for pr, author, kep_url in other_prs:
                note = extract_release_note(pr['body'])
                text = note if note else pr['title']
                f.write(format_line(text, pr['url'], author, kep_url) + "\n")
            f.write("\n")

        if deprecated_prs:
            f.write("## Deprecations\n")
            for pr, author, kep_url in deprecated_prs:
                note = extract_release_note(pr['body'])
                text = note if note else pr['title']
                f.write(format_line(text, pr['url'], author, kep_url) + "\n")

    print("""
========================================
Based on above information find one or two PRs which are of special interest to our readers. This could include PRs that do any of the following:

make significant changes to how Kubernetes is built or tested
re-organize the Kubernetes code or docs in a way that affects many contributors
introduce a brand-new, interesting feature
advance an interesting/major feature to GA
fix a difficult problem with Kubernetes that has been open for years
fix a major security vulnerability, particularly if changes to APIs are involved
introduce new and interesting tests or test suites
Bug fixes, test-only changes, doc-only changes, moving features to beta, refactorings, and similar "minor" PRs are generally not interesting and should not be in the Featured PR section. This does mean that some weeks, particularly during Code Freeze, there will be no PRs to feature.

The goal of the Featured PR section is to give readers in-depth coverage of one or two PRs, rather than trying to offer shallow coverage of all interesting PRs. Coverage of a featured PR should include:

names of contributors who worked on it
any KEPs it's linked to
links to any additional discussions, docs, or related issues
links to related (sub)projects and repositories
mentions of how the change will affect contributors and/or users
discussion of the history of the PR, if any
This section is formatted as a major section with subsections:
Write in 50 to 100 words in around 2 to 4 sentenaces

Example below for reference and must be in .md file format
```
## Featured PR format

### [139308: Introduce WatchListCompression (Beta)](https://github.com/kubernetes/kubernetes/pull/139308)

In this pull request [p0lyn0mial](https://github.com/p0lyn0mial) introduced the new **WatchListCompression** feature gate, bringing gzip compression support to Kubernetes WatchList responses when clients advertise `Accept-Encoding: gzip`. Since many controllers and operators perform an initial LIST before transitioning to WATCH, this feature can significantly reduce network bandwidth and improve efficiency in large clusters. Regular WATCH requests remain unchanged, making the rollout low risk for existing clients. This feature is enabled by default in Beta and is an important improvement for API server scalability.

### [139237: Evenly load balance admission webhook connections](https://github.com/kubernetes/kubernetes/pull/139237)

[aojea](https://github.com/aojea) improved how the kube-apiserver communicates with admission webhooks when `--enable-aggregator-routing=true` is enabled. Previously, HTTP connection reuse could unintentionally direct most concurrent admission requests to a single webhook backend, creating uneven load across replicas. This PR introduces round-trip load balancing between webhook endpoints through the **WebhookRoundTripLoadBalancing** feature gate (Beta, enabled by default), improving availability and scalability for highly available webhook deployments.

### [139282: Relaxed DNS Names reaches General Availability](https://github.com/kubernetes/kubernetes/pull/139282)

In this pull request [adrianmoisey](https://github.com/adrianmoisey) advanced **Relaxed DNS Names** to **General Availability**, completing the feature's journey from Alpha through Beta to a stable Kubernetes API. The work is part of [KEP-5311](https://github.com/kubernetes/enhancements/issues/5311), which expands supported DNS naming rules while maintaining compatibility with existing workloads. Reaching GA signals that the feature is production-ready and no longer experimental, allowing users and downstream projects to rely on it without feature gate concerns.
```

""")

    print(f"\nSuccessfully processed {len(prs)} PRs.")
    print(f"Report saved to: {output_file}")

    # Save print output to details_prs.txt
    details_file_path = "/tmp/details_prs.txt"
    try:
        with open(details_file_path, 'w') as df:
            df.writelines(_print_buffer)
    except Exception as e:
        builtins.print(f"Error saving detailed output to {details_file_path}: {e}")

    print(f"Detailed output saved to: {details_file_path}")
    print(f"\nWeek Ending {formatted_end_date}: Featured PRs")

if __name__ == "__main__":
    main()
