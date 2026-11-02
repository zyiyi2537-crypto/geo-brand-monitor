import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'
import { readFileSync, writeFileSync, mkdirSync } from 'fs'
import { join } from 'path'

/**
 * Post-build plugin: generates per-route HTML files with unique <title>,
 * <meta description>, <canonical>, and route-specific SEO skeleton content.
 *
 * This solves the SPA "duplicate content" problem for GEO checkers and AI
 * crawlers that don't execute JS: each route gets its own index.html with
 * unique metadata. nginx's `try_files $uri $uri/ /index.html` will serve
 * the route-specific file when it exists.
 */
function seoPages(): Plugin {
  const routes: Record<string, { title: string; description: string; h1: string; content: string }> = {
    '/geo-knowledge': {
      title: 'GEO Knowledge Base — AI Visibility Guides | Vigilath',
      description: 'Learn how Generative Engine Optimization works. Explore guides on robots.txt for AI bots, llms.txt, structured data, semantic HTML, and the 25 categories that determine your AI Visibility Score.',
      h1: 'GEO Knowledge Base — AI Visibility Guides',
      content: `
        <section>
          <h2>Understanding Generative Engine Optimization</h2>
          <p><dfn>Generative Engine Optimization</dfn> (<abbr title="Generative Engine Optimization">GEO</abbr>) is the practice of making web content discoverable and quotable by AI answer engines. This knowledge base covers every aspect of GEO — from technical crawl access (robots.txt, llms.txt, sitemap.xml) to content formatting that <abbr title="Large Language Models">LLMs</abbr> prefer to cite.</p>
          <h2>GEO Knowledge Categories</h2>
          <ul>
            <li><strong>Crawl Access</strong> — How to configure robots.txt, llms.txt, and .well-known manifests for AI bots like GPTBot, ClaudeBot, and PerplexityBot</li>
            <li><strong>Content Extractability</strong> — Server-side rendering, semantic HTML, heading structure, and content-to-HTML ratio</li>
            <li><strong>Meta &amp; Structured Data</strong> — JSON-LD schema markup, Open Graph, Twitter cards, and canonical URLs</li>
            <li><strong>Authority &amp; Trust</strong> — Security headers, E-E-A-T signals, brand entity knowledge graphs, and cross-platform presence</li>
            <li><strong>Answer-Format Readiness</strong> — Definitions, comparison tables, step-by-step instructions, FAQ blocks, and quotable statistics</li>
          </ul>
          <h2>GEO Metrics Explained</h2>
          <p>The AI Visibility Score (0–100) synthesizes 25 categories and 100+ discrete checks into a single actionable number. Each category targets a specific aspect of AI readiness — from whether your robots.txt allows GPTBot to whether your content includes citable definitions and comparison tables.</p>
        </section>`,
    },
    '/products-services': {
      title: 'Products & Services — GEO Audit Plans | Vigilath',
      description: 'Explore Vigilath membership plans: Free (3 checks/month), Pro ($9.99/mo, 20 audits), Starter ($999/mo, managed GEO), Growth ($2,500/mo, SEO placements), and Scale (enterprise). Get your AI Visibility Score today.',
      h1: 'Vigilath Products &amp; Services',
      content: `
        <section>
          <h2>Membership Plans</h2>
          <p>Vigilath offers five tiers designed for teams of every size — from solo founders to enterprise organizations managing hundreds of domains.</p>
          <table>
            <thead><tr><th>Plan</th><th>Price</th><th>Checks / month</th><th>Key features</th></tr></thead>
            <tbody>
              <tr><td>Free</td><td>$0</td><td>3</td><td>Basic 25-category audit, AI Visibility Score</td></tr>
              <tr><td>Pro</td><td>$9.99/mo</td><td>20</td><td>Full audit, check history, prioritized fix list, PDF export</td></tr>
              <tr><td>Starter</td><td>$999/mo</td><td>Unlimited</td><td>Managed GEO coverage, AI inclusion spec, copywriting compliance</td></tr>
              <tr><td>Growth</td><td>$2,500/mo</td><td>Unlimited</td><td>Starter features + paid SEO placements, priority technical support</td></tr>
              <tr><td>Scale</td><td>Custom</td><td>Unlimited</td><td>Enterprise GEO, reputation management, PR support, dedicated advisor</td></tr>
            </tbody>
          </table>
          <h2>Managed GEO Services</h2>
          <p>For Starter, Growth, and Scale tiers, Vigilath provides hands-on managed services: we implement the fixes our audit identifies — configuring robots.txt for AI bots, building JSON-LD structured data, creating llms.txt, and ensuring your content is formatted for maximum AI citation potential.</p>
        </section>`,
    },
    '/about': {
      title: 'About Vigilath — Our Mission & Team',
      description: 'Vigilath is the unified GEO+AEO platform helping websites achieve global AI visibility. Learn about our team, mission, and the technology behind the AI Visibility Score.',
      h1: 'About Vigilath',
      content: `
        <section>
          <h2>Our Mission</h2>
          <p>Vigilath was founded to solve a new challenge in digital marketing: making websites visible to AI answer engines. As ChatGPT, Perplexity, Claude, and Google AI Overviews reshape how people find information, we provide the tools and expertise to ensure your brand is cited, quoted, and recommended by these platforms.</p>
          <h2>What We Do</h2>
          <p>We built the first unified <abbr title="Generative Engine Optimization">GEO</abbr>+<abbr title="Answer Engine Optimization">AEO</abbr> audit platform. Vigilath scans any website across 25 categories and 100+ signals, producing a 0–100 AI Visibility Score with a detailed category breakdown and prioritized fix list. Our managed services help teams implement those fixes at scale.</p>
        </section>`,
    },
    '/privacy': {
      title: 'Privacy Policy | Vigilath',
      description: 'Vigilath Privacy Policy. Learn how we collect, use, and protect your personal information when using the Vigilath GEO Readiness Checker platform.',
      h1: 'Privacy Policy',
      content: `
        <section>
          <h2>1. Overview</h2>
          <p>Vigilath (operated by Zen7) values your privacy. This Privacy Policy explains how we collect, use, and protect your personal information when you use the Vigilath GEO Readiness Checker (the "Service").</p>
          <h2>2. Information We Collect</h2>
          <p>We collect information you provide directly (account registration, contact forms) and information collected automatically (usage data, device information, cookies). We do not sell your personal data to third parties.</p>
          <h2>3. How We Use Information</h2>
          <p>We use your information to provide and improve the Service, process transactions, send communications, and ensure security. For full details, please refer to the complete policy rendered on this page.</p>
          <h2>4. Contact</h2>
          <p>For privacy inquiries, contact us at support@zen7.com or visit our <a href="/contact">contact page</a>.</p>
        </section>`,
    },
    '/terms': {
      title: 'Terms of Service | Vigilath',
      description: 'Vigilath Terms of Service. Read the terms governing your use of the Vigilath GEO+AEO platform, including membership plans, acceptable use, and intellectual property.',
      h1: 'Terms of Service',
      content: `
        <section>
          <h2>1. Acceptance of Terms</h2>
          <p>By accessing or using Vigilath (the "Service"), you agree to be bound by these Terms of Service. If you do not agree, do not use the Service.</p>
          <h2>2. Service Description</h2>
          <p>Vigilath provides a Generative Engine Optimization (GEO) readiness checking service that audits websites across 25 categories to assess AI visibility. The Service includes free and paid membership tiers.</p>
          <h2>3. Membership &amp; Billing</h2>
          <p>Paid plans (Pro, Starter, Growth, Scale) are billed on a recurring basis. You may cancel at any time; cancellations take effect at the end of the current billing period.</p>
          <h2>4. Contact</h2>
          <p>For questions about these terms, contact us at support@zen7.com or visit our <a href="/contact">contact page</a>.</p>
        </section>`,
    },
    '/membership': {
      title: 'Membership Plans — Free, Pro, Starter, Growth, Scale | Vigilath',
      description: 'Compare Vigilath membership plans. Free plan includes 3 checks/month. Pro offers 20 full audits for $9.99/mo. Starter, Growth, and Scale tiers include managed GEO services and unlimited checks.',
      h1: 'Vigilath Membership Plans',
      content: `
        <section>
          <h2>Choose Your AI Visibility Plan</h2>
          <p>Every plan includes the core Vigilath 25-category audit. Higher tiers unlock more checks, managed services, and enterprise features.</p>
          <table>
            <thead><tr><th>Plan</th><th>Price</th><th>Checks</th><th>Fix list</th><th>History</th><th>Managed GEO</th><th>Dedicated advisor</th></tr></thead>
            <tbody>
              <tr><td>Free</td><td>$0</td><td>3/mo</td><td>Basic</td><td>No</td><td>No</td><td>No</td></tr>
              <tr><td>Pro</td><td>$9.99/mo</td><td>20/mo</td><td>Full</td><td>Yes</td><td>No</td><td>No</td></tr>
              <tr><td>Starter</td><td>$999/mo</td><td>Unlimited</td><td>Full</td><td>Yes</td><td>Yes</td><td>No</td></tr>
              <tr><td>Growth</td><td>$2,500/mo</td><td>Unlimited</td><td>Full</td><td>Yes</td><td>Yes</td><td>No</td></tr>
              <tr><td>Scale</td><td>Custom</td><td>Unlimited</td><td>Full</td><td>Yes</td><td>Yes</td><td>Yes</td></tr>
            </tbody>
          </table>
          <h2>Frequently Asked Questions</h2>
          <ul>
            <li><strong>Can I upgrade anytime?</strong> — Yes, plan upgrades are prorated and take effect immediately.</li>
            <li><strong>Is there a free trial?</strong> — The Free plan is always free. Pro offers a 7-day trial.</li>
            <li><strong>What payment methods are accepted?</strong> — Credit cards (Visa, Mastercard, Amex) via Stripe.</li>
          </ul>
        </section>`,
    },
    '/contact': {
      title: 'Contact Us | Vigilath',
      description: 'Get in touch with the Vigilath team for sales inquiries, technical support, or partnership opportunities. We respond within 24 hours.',
      h1: 'Contact Vigilath',
      content: `
        <section>
          <h2>Get in Touch</h2>
          <p>Have questions about GEO, need help with your AI visibility audit, or interested in our managed services? Our team is here to help.</p>
          <ul>
            <li><strong>Email:</strong> support@zen7.com</li>
            <li><strong>Response time:</strong> Within 24 hours on business days</li>
          </ul>
          <h2>What can we help with?</h2>
          <ul>
            <li>Technical support for Vigilath audits and reports</li>
            <li>Sales inquiries for Starter, Growth, and Scale plans</li>
            <li>Partnership and integration opportunities</li>
            <li>Press and media inquiries</li>
          </ul>
        </section>`,
    },
    '/cookie-policy': {
      title: 'Cookie Policy | Vigilath',
      description: 'How Vigilath uses cookies and browser storage. Essential localStorage (auth token, user, language, theme) plus third-party Stripe (payments) and Cloudflare (security) cookies — and how to manage them.',
      h1: 'Cookie Policy',
      content: `
        <section>
          <h2>1. What Are Cookies</h2>
          <p>Cookies are small text files stored on your device by websites to remember preferences and improve your experience. Vigilath also uses browser storage technologies such as <code>localStorage</code>.</p>
          <h2>2. Cookies &amp; Storage We Use</h2>
          <p><strong>Essential storage</strong> (localStorage): <code>token</code> (authentication), <code>user</code> (current user basic info), <code>i18nextLng</code> (language preference), <code>theme</code> (light/dark preference).</p>
          <p><strong>Third-party cookies:</strong> Stripe — used on the payment checkout page for fraud detection and payment processing; Cloudflare — security and performance (e.g. <code>__cf_bm</code> for bot detection).</p>
          <h2>3. How to Manage Cookies</h2>
          <p>You can manage or delete cookies and localStorage data through your browser settings (Chrome, Firefox, Safari). Disabling essential storage may require you to log in again or prevent some features from working properly.</p>
          <h2>4. Contact Us</h2>
          <p>Questions about this Cookie Policy? Email <a href="mailto:support@zen7.com">support@zen7.com</a>.</p>
        </section>`,
    },
    '/faq': {
      title: 'FAQ — GEO &amp; AI Visibility Questions Answered | Vigilath',
      description: 'Answers to the questions buyers ask most about Vigilath: how GEO differs from SEO, which AI engines are covered, time to results, pricing, the 8-step growth pipeline, and sentiment monitoring.',
      h1: 'Frequently Asked Questions',
      content: `
        <section>
          <h2>Frequently Asked Questions</h2>
          <h3>How is GEO different from SEO?</h3>
          <p>GEO (Generative Engine Optimization) focuses on getting your brand recommended by AI assistants like ChatGPT, Gemini, and Perplexity. SEO focuses on ranking in search engine results. GEO is designed for the AI-search era and complements — not replaces — SEO.</p>
          <h3>How long until I see results?</h3>
          <p>Depending on your industry and competition, clients usually see AI mention rate and citation lift improving in 1–3 months and reach full optimization in 3–6 months. Our cockpit produces a visibility curve daily so you can track quantitatively.</p>
          <h3>Which AI engines do you cover?</h3>
          <p>All major Western engines (ChatGPT / Gemini / Perplexity / Claude / DeepSeek) and CN engines (Baidu AI / Wenxin / Qwen / Doubao / Yuanbao). New engines are onboarded within 2 weeks if they expose an API or can be crawled.</p>
          <h3>How is the 8-step pipeline different from a traditional SEO agency?</h3>
          <p>Traditional SEO is manual: keyword → content → backlinks → wait for ranking. The 8-step pipeline closes the loop automatically — from seed expansion, clustering, drafting, distribution, to AI indexing verification, citation monitoring, and feedback refinement.</p>
          <h3>Is sentiment monitoring real-time?</h3>
          <p>Currently daily batch collection plus instant alerts. We scan 42 CN/global trending sources (Weibo, Zhihu, Douyin, Toutiao, Reddit, HN, etc.). When negative coverage or keyword hits are detected, alerts go out within 15 minutes via email and in-app notification.</p>
          <h3>Can I self-serve, or do I need to talk to sales?</h3>
          <p>The free tier self-serves a 25-category GEO audit and crawler accessibility test. Membership unlocks all advanced checks. The 8-step pipeline plus content distribution is a growth service requiring a sales engagement.</p>
          <h3>What does it cost?</h3>
          <p>GEO self-serve membership starts low per month. The 8-step growth service is priced per project depending on industry, target engines, and content output. Contact sales for a custom quote.</p>
          <h3>Do you offer ongoing maintenance?</h3>
          <p>Yes — required, because AI engines' algorithms, crawl preferences, and ranking rules change continuously. Monthly maintenance includes model upgrade tracking, monitored-question refresh, content strategy adjustment, and citation-position defense.</p>
        </section>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
          {"@type":"Question","name":"How is GEO different from SEO?","acceptedAnswer":{"@type":"Answer","text":"GEO (Generative Engine Optimization) focuses on getting your brand recommended by AI assistants like ChatGPT, Gemini, and Perplexity. SEO focuses on ranking in search engine results. GEO complements — not replaces — SEO."}},
          {"@type":"Question","name":"How long until I see results?","acceptedAnswer":{"@type":"Answer","text":"Clients usually see AI mention rate and citation lift improving in 1–3 months and reach full optimization in 3–6 months, tracked daily via a visibility curve."}},
          {"@type":"Question","name":"Which AI engines do you cover?","acceptedAnswer":{"@type":"Answer","text":"All major Western engines (ChatGPT, Gemini, Perplexity, Claude, DeepSeek) and CN engines (Baidu AI, Wenxin, Qwen, Doubao, Yuanbao)."}},
          {"@type":"Question","name":"Can I self-serve, or do I need to talk to sales?","acceptedAnswer":{"@type":"Answer","text":"The free tier self-serves a 25-category GEO audit. Membership unlocks advanced checks. The 8-step growth pipeline is a managed service requiring a sales engagement."}},
          {"@type":"Question","name":"Do you offer ongoing maintenance?","acceptedAnswer":{"@type":"Answer","text":"Yes. Monthly maintenance includes model upgrade tracking, monitored-question refresh, content strategy adjustment, and citation-position defense."}}
        ]}
        </script>`,
    },
    '/pricing': {
      title: 'Pricing — GEO Membership &amp; Growth Plans | Vigilath',
      description: 'Compare Vigilath plans: Free (3 checks/month), Pro ($9.99/mo, 20 audits), Starter ($999/mo, managed GEO), Growth ($2,500/mo, SEO placements), and Scale (enterprise, custom).',
      h1: 'Vigilath Pricing',
      content: `
        <section>
          <h2>Membership Plans</h2>
          <p>Every plan includes the core 25-category audit. Higher tiers unlock more checks, managed services, and enterprise features.</p>
          <table>
            <thead><tr><th>Plan</th><th>Price</th><th>Checks / month</th><th>Key features</th></tr></thead>
            <tbody>
              <tr><td>Free</td><td>$0</td><td>3</td><td>Basic 25-category audit, AI Visibility Score</td></tr>
              <tr><td>Pro</td><td>$9.99/mo</td><td>20</td><td>Full audit, check history, prioritized fix list, PDF export</td></tr>
              <tr><td>Starter</td><td>$999/mo</td><td>Unlimited</td><td>Managed GEO coverage, AI inclusion spec, copywriting compliance</td></tr>
              <tr><td>Growth</td><td>$2,500/mo</td><td>Unlimited</td><td>Starter features + paid SEO placements, priority support</td></tr>
              <tr><td>Scale</td><td>Custom</td><td>Unlimited</td><td>Enterprise GEO, reputation management, dedicated advisor</td></tr>
            </tbody>
          </table>
        </section>`,
    },
    '/process': {
      title: 'How Vigilath Works — The GEO Audit Process | Vigilath',
      description: 'Vigilath\'s process: enter a URL, run a 25-category / 100+ signal audit across crawl access, content extractability, structured data, authority, and answer-format readiness, then get a 0–100 AI Visibility Score and a prioritized fix list.',
      h1: 'How Vigilath Works',
      content: `
        <section>
          <h2>From URL to AI Visibility Score</h2>
          <ol>
            <li><strong>Enter a URL</strong> — point Vigilath at any website or landing page.</li>
            <li><strong>Audit 25 categories / 100+ signals</strong> — across crawl access, content extractability, meta &amp; structured data, authority &amp; trust, and answer-format readiness.</li>
            <li><strong>Score</strong> — receive a 0–100 AI Visibility Score and a letter grade.</li>
            <li><strong>Category breakdown</strong> — see exactly which signals pass, warn, or fail.</li>
            <li><strong>Prioritized fix list</strong> — actionable recommendations ranked by impact.</li>
            <li><strong>Optimize</strong> — self-serve the fixes, or hand off to Vigilath's managed GEO / AEO services.</li>
          </ol>
        </section>`,
    },
    '/data': {
      title: 'AI Visibility Data &amp; Metrics — How the Score Works | Vigilath',
      description: 'Understand Vigilath\'s metrics: the 0–100 AI Visibility Score, the 25-category breakdown, 100+ signals, AI citation frequency, and answer-inclusion rate across ChatGPT, Perplexity, Claude, and Google AI Overviews.',
      h1: 'AI Visibility Data &amp; Metrics',
      content: `
        <section>
          <h2>What the Numbers Mean</h2>
          <p>The <strong>AI Visibility Score</strong> (0–100) synthesizes 25 categories and 100+ discrete checks into a single actionable number, paired with a letter grade.</p>
          <ul>
            <li><strong>25-category breakdown</strong> — every category targets a specific aspect of AI readiness, from robots.txt access to citable content shapes.</li>
            <li><strong>Citation frequency</strong> — how often AI engines quote or reference your domain.</li>
            <li><strong>Answer-inclusion rate</strong> — how often your brand appears in AI-generated answers across ChatGPT, Perplexity, Claude, and Google AI Overviews.</li>
            <li><strong>Daily visibility curve</strong> — track movement over time as fixes land and engines re-crawl.</li>
          </ul>
        </section>`,
    },
  }

  return {
    name: 'seo-pages',
    apply: 'build',
    closeBundle() {
      const distDir = join(process.cwd(), 'dist')
      let html: string
      try {
        html = readFileSync(join(distDir, 'index.html'), 'utf-8')
      } catch {
        return // dist/index.html not yet built
      }

      for (const [route, meta] of Object.entries(routes)) {
        const dir = join(distDir, route.slice(1)) // e.g. dist/geo-knowledge
        mkdirSync(dir, { recursive: true })

        let page = html
        // Replace <title>
        page = page.replace(
          /<title>[^<]*<\/title>/,
          `<title>${meta.title}</title>`,
        )
        // Replace meta description
        page = page.replace(
          /<meta name="description" content="[^"]*"/,
          `<meta name="description" content="${meta.description}"`,
        )
        // Replace canonical
        page = page.replace(
          /<link rel="canonical" href="[^"]*"/,
          `<link rel="canonical" href="https://www.vigilath.com${route}"`,
        )
        // Replace og:title
        page = page.replace(
          /<meta property="og:title" content="[^"]*"/,
          `<meta property="og:title" content="${meta.title}"`,
        )
        // Replace og:description
        page = page.replace(
          /<meta property="og:description" content="[^"]*"/,
          `<meta property="og:description" content="${meta.description}"`,
        )
        // Replace og:url
        page = page.replace(
          /<meta property="og:url" content="[^"]*"/,
          `<meta property="og:url" content="https://www.vigilath.com${route}"`,
        )
        // Replace twitter:title
        page = page.replace(
          /<meta name="twitter:title" content="[^"]*"/,
          `<meta name="twitter:title" content="${meta.title}"`,
        )
        // Replace twitter:description
        page = page.replace(
          /<meta name="twitter:description" content="[^"]*"/,
          `<meta name="twitter:description" content="${meta.description}"`,
        )
        // Replace SEO skeleton content (between <article> tags)
        page = page.replace(
          /<article>[\s\S]*?<\/article>/,
          `<article><h1>${meta.h1}</h1>${meta.content}</article>`,
        )
        // Update breadcrumb
        page = page.replace(
          /<nav aria-label="Breadcrumb">[\s\S]*?<\/nav>/,
          `<nav aria-label="Breadcrumb"><ol><li><a href="/">Home</a></li><li><a href="${route}">${meta.h1.replace(/&amp;/g, '&')}</a></li></ol></nav>`,
        )

        writeFileSync(join(dir, 'index.html'), page)
      }
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), seoPages()],
  cacheDir: '.vite/build-cache',
  build: {
    outDir: 'dist',
    sourcemap: false,
    minify: 'terser',
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) {
            return 'vendor';
          }
          if (id.includes('node_modules/react-router-dom')) {
            return 'router';
          }
          if (id.includes('node_modules/i18next') || id.includes('node_modules/react-i18next')) {
            return 'i18n';
          }
          if (id.includes('node_modules/@radix-ui/react-tooltip')) {
            return 'ui';
          }
        }
      },
      plugins: [
        // Analysis artifact lives outside dist/ so it never ships to webroot.
        // open:false — on headless/EC2 build env, opening a browser hangs.
        // Run `npx vite build && xdg-open stats.html` locally to view.
        visualizer({
          open: false,
          filename: 'stats.html'
        })
      ]
    }
  },
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY || 'http://localhost:8070',
        changeOrigin: true,
      },
      '/pay': {
        target: 'http://localhost:3010',
        changeOrigin: true,
      },
    },
  }
})
