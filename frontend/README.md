# Vigilath Frontend

The frontend is a React 19 and TypeScript single-page application built with
Vite.

## Stack

- React 19 and React Router
- TypeScript
- Vite
- TanStack Query and Axios
- i18next
- Recharts
- jsPDF, docx, and html2canvas
- ethers and QR-code rendering for payment flows

## Development

```bash
npm ci
npm run dev
```

The development server listens on `http://localhost:3000`. Requests under
`/api` are proxied to the local FastAPI backend on port 8070.

## Commands

```bash
npm run dev
npm run lint
npm run build
npm run preview
```

The production build also generates route-specific HTML metadata and static
SEO content through the custom plugin in `vite.config.ts`.

## Structure

- `src/pages/`: route-level screens
- `src/components/`: reusable UI and feature components
- `src/services/`: backend API clients
- `src/hooks/` and `src/contexts/`: shared state and behavior
- `src/i18n/`: language resources
- `src/types/`: shared TypeScript types

Do not put credentials in `VITE_*` variables: Vite embeds those values in
browser bundles.
