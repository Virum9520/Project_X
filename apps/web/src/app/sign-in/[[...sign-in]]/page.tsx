import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-6 pb-16 pt-28">
      <SignIn fallbackRedirectUrl="/account" />
    </main>
  );
}
