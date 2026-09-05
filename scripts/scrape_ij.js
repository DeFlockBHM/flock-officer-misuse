#!/usr/bin/env node
// Scrapes the Institute for Justice's ALPR abuse database and writes
// data/cases.json. Pure HTTP/DOM scraping - no LLM calls. See SCHEMA.md.
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright-extra');
const stealth = require('puppeteer-extra-plugin-stealth')();
chromium.use(stealth);

const SOURCE_URL = 'https://ij.org/the-ij-database-of-alpr-abuse/';
const SOURCE_NAME = 'Institute for Justice - IJ Database of ALPR Abuse';
const DATA_DIR = path.join(__dirname, '..', 'data');
const CASES_PATH = path.join(DATA_DIR, 'cases.json');
const RUN_LOG_DIR = path.join(DATA_DIR, 'run-log');

const CLASSIFICATION_MAP = {
  'stalking': 'stalking',
  'non-law-enforcement-use': 'non_law_enforcement_use',
  'other-misuse': 'other_misuse',
  'error': 'error',
};

// Ordered so more specific phrases are checked before shorter substrings
// they might otherwise be shadowed by (e.g. "pleaded guilty" before a bare
// "guilty" match would ever be introduced).
const OUTCOME_RULES = [
  ['fired', ['fired', 'terminated']],
  ['resigned', ['resigned']],
  ['retired', ['retired']],
  ['arrested', ['arrested']],
  ['pleaded_guilty', ['pled guilty', 'pleaded guilty']],
  ['charged', ['charged', 'indicted']],
  ['convicted', ['convicted']],
  ['sentenced', ['sentenced', 'sentence of']],
  ['suspended', ['suspended']],
  ['administrative_leave', ['administrative leave', 'placed on leave', 'put on leave']],
  ['demoted', ['demoted']],
  ['disciplined', ['disciplinary action', 'corrective action', 'reprimand']],
  ['access_revoked', ['access revoked', 'revoked access', 'access was suspended', 'access to the flock system']],
  ['under_investigation', ['under investigation', 'investigation is ongoing', 'being investigated', 'under review']],
];

function decodeEntities(str) {
  if (!str) return str;
  return str
    .replace(/&amp;#8211;/g, '-')
    .replace(/&#8211;/g, '-')
    .replace(/&amp;/g, '&')
    .replace(/&#8217;/g, '’')
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'");
}

function slugify(str) {
  return str
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

async function fetchRenderedHtml() {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
        '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    });
    await page.goto(SOURCE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
    // The page sits behind a Cloudflare JS challenge; give it time to clear
    // and the incident list (client-rendered) time to populate.
    await page.waitForSelector('.alpr-incident-tracker__incident', { timeout: 30000 });
    await page.waitForTimeout(1500);
    return await page.content();
  } finally {
    await browser.close();
  }
}

function parseIncidents(html) {
  const chunks = html.split('<article class="alpr-incident-tracker__incident"').slice(1);
  const incidents = [];
  for (const chunk of chunks) {
    const attr = (name) => {
      const m = chunk.match(new RegExp(`data-${name}="([^"]*)"`));
      return m ? decodeEntities(m[1]) : null;
    };
    const manufacturer = attr('manufacturer');
    const manufacturer_name = attr('manufacturer-name');

    const descMatch = chunk.match(/alpr-incident-tracker__description"><p>([\s\S]*?)<\/p>/);
    const sourceMatch = chunk.match(/alpr-incident-tracker__source" href="([^"]+)"/);
    const dateTextMatch = chunk.match(/<dt>Date<\/dt>\s*<dd>([^<]*)<\/dd>/);
    const description = descMatch ? decodeEntities(descMatch[1].replace(/<[^>]+>/g, '').trim()) : '';

    incidents.push({
      ij_source_id: attr('alpr-incident'),
      title: attr('title'),
      location: {
        city: attr('location'),
        state: attr('state'),
        state_name: attr('state-name'),
      },
      date: {
        text: dateTextMatch ? decodeEntities(dateTextMatch[1].trim()) : null,
        iso: attr('date'),
      },
      classification_raw: attr('type-name'),
      classification: CLASSIFICATION_MAP[attr('type')] || 'other_misuse',
      manufacturer,
      manufacturer_name,
      is_flock: manufacturer === 'flock',
      description,
      source_url: sourceMatch ? sourceMatch[1] : null,
    });
  }
  return incidents;
}

function tagOutcomes(description) {
  const lower = description.toLowerCase();
  const outcomes = [];
  const matches = [];
  for (const [outcome, keywords] of OUTCOME_RULES) {
    for (const kw of keywords) {
      if (lower.includes(kw)) {
        outcomes.push(outcome);
        matches.push(kw);
        break;
      }
    }
  }
  if (outcomes.length === 0) {
    outcomes.push('no_action_reported');
  }
  return { outcomes, outcome_matches: matches };
}

function contentHash(incident) {
  const material = [
    incident.classification_raw || '',
    incident.description || '',
    incident.source_url || '',
    incident.date.iso || '',
  ].join('|');
  return 'sha256:' + crypto.createHash('sha256').update(material).digest('hex');
}

function buildId(incident) {
  const state = slugify(incident.location.state || 'unknown');
  const city = slugify(incident.location.city || 'unknown');
  return `${state}-${city}-${incident.ij_source_id}`;
}

function loadPrevious() {
  if (!fs.existsSync(CASES_PATH)) return null;
  try {
    return JSON.parse(fs.readFileSync(CASES_PATH, 'utf8'));
  } catch (e) {
    console.error('Could not parse existing cases.json, treating as empty:', e.message);
    return null;
  }
}

function merge(scraped, previous) {
  const now = new Date().toISOString();
  const prevById = new Map();
  if (previous && Array.isArray(previous.incidents)) {
    for (const inc of previous.incidents) prevById.set(inc.ij_source_id, inc);
  }

  const seenIds = new Set();
  const merged = [];
  let added = 0;
  let updated = 0;
  let unchanged = 0;

  for (const raw of scraped) {
    const { outcomes, outcome_matches } = tagOutcomes(raw.description);
    const incident = {
      id: buildId(raw),
      ij_source_id: raw.ij_source_id,
      title: raw.title,
      location: raw.location,
      date: raw.date,
      classification: raw.classification,
      classification_raw: raw.classification_raw,
      manufacturer: raw.manufacturer,
      manufacturer_name: raw.manufacturer_name,
      is_flock: raw.is_flock,
      description: raw.description,
      source_url: raw.source_url,
      outcomes,
      outcome_matches,
      content_hash: null,
      first_seen_at: now,
      last_seen_at: now,
      status: 'active',
      verified: false,
    };
    incident.content_hash = contentHash(incident);
    seenIds.add(incident.ij_source_id);

    const prev = prevById.get(incident.ij_source_id);
    if (prev) {
      incident.first_seen_at = prev.first_seen_at || now;
      incident.verified = prev.verified || false;
      if (prev.content_hash === incident.content_hash && prev.status === 'active') {
        incident.last_seen_at = prev.last_seen_at;
        unchanged++;
      } else {
        incident.last_seen_at = now;
        updated++;
      }
    } else {
      added++;
    }
    merged.push(incident);
  }

  let removed = 0;
  if (previous && Array.isArray(previous.incidents)) {
    for (const inc of previous.incidents) {
      if (!seenIds.has(inc.ij_source_id)) {
        merged.push({ ...inc, status: 'removed_from_source', last_seen_at: inc.last_seen_at });
        removed++;
      }
    }
  }

  merged.sort((a, b) => (b.date.iso || '').localeCompare(a.date.iso || ''));

  return { merged, stats: { added, updated, unchanged, removed, total: merged.length } };
}

async function main() {
  console.log(`Fetching ${SOURCE_URL} ...`);
  const html = await fetchRenderedHtml();
  const scraped = parseIncidents(html);
  const flockCount = scraped.filter((i) => i.is_flock).length;
  console.log(`Parsed ${scraped.length} ALPR incidents from IJ's database (${flockCount} Flock).`);

  const previous = loadPrevious();
  const { merged, stats } = merge(scraped, previous);

  const output = {
    schema_version: 3,
    generated_at: new Date().toISOString(),
    source_url: SOURCE_URL,
    source_name: SOURCE_NAME,
    count: merged.length,
    incidents: merged,
  };

  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(CASES_PATH, JSON.stringify(output, null, 2) + '\n');

  const manufacturerCounts = {};
  for (const inc of merged) {
    if (inc.status !== 'active') continue;
    manufacturerCounts[inc.manufacturer_name || 'Unknown'] =
      (manufacturerCounts[inc.manufacturer_name || 'Unknown'] || 0) + 1;
  }

  fs.mkdirSync(RUN_LOG_DIR, { recursive: true });
  const dateStr = new Date().toISOString().slice(0, 10);
  const logPath = path.join(RUN_LOG_DIR, `${dateStr}.md`);
  const logLines = [
    `# IJ ALPR scrape - ${dateStr}`,
    '',
    `- Added: ${stats.added}`,
    `- Updated: ${stats.updated}`,
    `- Unchanged: ${stats.unchanged}`,
    `- Removed from source (flagged, not deleted): ${stats.removed}`,
    `- Total active + removed entries: ${stats.total}`,
    '',
    '## By manufacturer (active entries)',
    '',
    ...Object.entries(manufacturerCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([name, n]) => `- ${name}: ${n}`),
    '',
  ];
  fs.writeFileSync(logPath, logLines.join('\n') + '\n');

  console.log(JSON.stringify(stats, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
