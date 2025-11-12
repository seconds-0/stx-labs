import type { GetServerSideProps } from 'next';

export const getServerSideProps: GetServerSideProps = async ({ res }) => {
  res.writeHead(302, { Location: '/index.html' });
  res.end();
  return { props: {} };
};

export default function RedirectPage() {
  return null;
}
