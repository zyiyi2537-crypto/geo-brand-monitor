import { Helmet } from 'react-helmet-async';
import { useTranslation } from 'react-i18next';

type Props = {
  titleKey: string;
  descriptionKey?: string;
  titleFallback?: string;
  descriptionFallback?: string;
};

export function PageHead({
  titleKey,
  descriptionKey,
  titleFallback,
  descriptionFallback,
}: Props) {
  const { t } = useTranslation();
  const title = t(titleKey, titleFallback ?? '') as string;
  const description = descriptionKey
    ? (t(descriptionKey, descriptionFallback ?? '') as string)
    : undefined;

  return (
    <Helmet>
      {title && <title>{title}</title>}
      {title && <meta property="og:title" content={title} />}
      {title && <meta name="twitter:title" content={title} />}
      {description && <meta name="description" content={description} />}
      {description && <meta property="og:description" content={description} />}
      {description && <meta name="twitter:description" content={description} />}
    </Helmet>
  );
}
