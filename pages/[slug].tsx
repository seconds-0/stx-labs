import type { GetServerSideProps } from 'next';

const SUPPORTED_SLUGS = new Set([
  'wallet',
  'value',
  'macro',
  'roi',
  'coinbase',
  'coinbase_replacement',
  'scenarios',
]);

export const getServerSideProps: GetServerSideProps = async ({ params, res }) => {
  const slugParam = params?.slug;
  const slug = Array.isArray(slugParam) ? slugParam[0] : slugParam;

  if (slug && SUPPORTED_SLUGS.has(slug)) {
    res.writeHead(302, { Location: `/${slug}/index.html` });
    res.end();
    return { props: {} };
  }

  return {
    notFound: true,
  };
};

export default function DashboardRedirectPage() {
  return null;
}
