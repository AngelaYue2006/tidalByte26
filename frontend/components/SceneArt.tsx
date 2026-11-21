type Props = {
  name: "care" | "phone" | "calendar" | "family";
  className?: string;
  alt?: string;
};

const SRC: Record<Props["name"], string> = {
  care: "/illustrations/care.svg",
  phone: "/illustrations/phone.svg",
  calendar: "/illustrations/calendar.svg",
  family: "/illustrations/family.svg",
};

/** Decorative filler illustration for page heroes. */
export default function SceneArt({ name, className, alt }: Props) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={SRC[name]}
      alt={alt ?? ""}
      className={className ?? "scene-art"}
      width={320}
      height={240}
      decoding="async"
    />
  );
}
