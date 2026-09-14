const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** '2026-06-08' -> 'Jun 8, 2026' (string split, so no timezone shift) */
export function formatIsoDate(isoDate: string): string {
  const [year, month, day] = isoDate.split('-')
  return `${MONTH_NAMES[Number(month) - 1]} ${Number(day)}, ${year}`
}

/** 'date validity' -> 'Date Validity' */
export function titleCase(text: string): string {
  return text.replace(/\b\w/g, firstLetter => firstLetter.toUpperCase())
}

/** 'LinkedIn Ads' -> 'linkedin', used for the platform colour classes */
export function platformSlug(platform: string): string {
  return platform.split(' ')[0].toLowerCase()
}
