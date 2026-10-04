import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-16">
      <p className="text-sm uppercase tracking-[0.3em] text-glow">Owner Console</p>
      {/* No self-serve sign-up here: owners come from ADMIN_OWNER_EMAILS. */}
      <SignIn
        withSignUp={false}
        fallbackRedirectUrl="/"
        appearance={{ elements: { footerAction: { display: "none" } } }}
      />
    </main>
  );
}
