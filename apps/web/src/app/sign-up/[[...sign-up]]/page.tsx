import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-6 pb-16 pt-28">
      <SignUp fallbackRedirectUrl="/onboarding" />
    </main>
  );
}
