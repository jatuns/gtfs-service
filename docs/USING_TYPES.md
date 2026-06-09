# TypeScript Tipleri Kullanım Rehberi

`docs/api-types.ts` dosyası, OpenAPI şemasından otomatik üretilen
TypeScript tiplerini içerir. Bu sayede frontend ekibi backend ile
**tipli** konuşur — yanlış alan adı, eksik parametre, yanlış tip
gibi hataları derleme zamanında yakalar.

## Üretim

```bash
# Uvicorn çalışır halde:
npx openapi-typescript@7 http://localhost:8000/openapi.json -o docs/api-types.ts
```

Backend şeması değiştiğinde komutu tekrar çalıştır.

## Kullanım — fetch örneği

```typescript
import type { paths } from "./api-types";

// Endpoint'in cevap tipini al
type StopArrivalsResponse =
  paths["/stops/{stop_id}/arrivals"]["get"]["responses"]["200"]["content"]["application/json"];

async function getArrivals(stopId: string, date: string) {
  const url = new URL(`/stops/${stopId}/arrivals`, "http://localhost:8000");
  url.searchParams.set("date", date);

  const r = await fetch(url);
  const data: StopArrivalsResponse = await r.json();

  // Artık tipli kullanırsın
  console.log(data.stop_name);          // string | null
  console.log(data.arrival_count);      // number
  data.arrivals.forEach(a => {
    console.log(a.arrival_time);        // string
    console.log(a.route_id);            // string
  });
}
```

## Daha kolay kullanım — openapi-fetch

`openapi-fetch` paketi tipli istek atmayı tek satıra indirir:

```bash
npm install openapi-fetch
```

```typescript
import createClient from "openapi-fetch";
import type { paths } from "./api-types";

const client = createClient<paths>({ baseUrl: "http://localhost:8000" });

const { data, error } = await client.GET("/stops/{stop_id}/arrivals", {
  params: {
    path: { stop_id: "D0052" },
    query: { date: "2026-04-15", from_time: "08:00:00" },
  },
});

if (error) {
  // error: HTTPValidationError tipli
} else {
  // data: StopArrivalsResponse tipli — IDE otomatik tamamlar
  console.log(data.arrival_count);
}
```

## CI'da otomatik güncelleme

İleride frontend ekibi ayrı repo'da çalışıyorsa, her backend push'unda
`api-types.ts`'i yeniden üretip frontend repo'suna PR açan bir GitHub
Action eklenebilir. Bu sayede backend ↔ frontend kontratı **canlı**
kalır.
