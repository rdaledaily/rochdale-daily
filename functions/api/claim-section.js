/** Stripe-hosted checkout for the homepage local-services sponsorship.
 * Required Cloudflare secrets: STRIPE_SECRET_KEY, STRIPE_SECTION_PRICE_ID.
 * The price is configured in Stripe, never supplied by the visitor.
 */
export async function onRequestPost({request,env}) {
  const respond=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
  if (!env.STRIPE_SECRET_KEY || !env.STRIPE_SECTION_PRICE_ID) {
    return respond({error:"Checkout is not configured yet. Please contact advertising@rochdaledaily.co.uk."},503);
  }
  if (Number(request.headers.get("content-length")||0)>4096) return respond({error:"Request too large"},413);
  let data;
  try { data=await request.json(); } catch {return respond({error:"Invalid request"},400);}
  const business=String(data.business||"").trim().slice(0,100);
  const email=String(data.email||"").trim().slice(0,150);
  if (business.length<2 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return respond({error:"Enter a business name and valid email"},400);
  const origin=new URL(request.url).origin;
  const body=new URLSearchParams();
  body.set("mode","payment");
  body.set("line_items[0][price]",env.STRIPE_SECTION_PRICE_ID);
  body.set("line_items[0][quantity]","1");
  body.set("customer_email",email);
  body.set("client_reference_id","rd-local-section");
  body.set("metadata[business]",business);
  body.set("metadata[placement]","local-services-section");
  body.set("success_url",origin+"/claim-section.html?checkout=success");
  body.set("cancel_url",origin+"/claim-section.html?checkout=cancelled");
  try {
    const response=await fetch("https://api.stripe.com/v1/checkout/sessions",{
      method:"POST",
      headers:{"Authorization":"Bearer "+env.STRIPE_SECRET_KEY,"Content-Type":"application/x-www-form-urlencoded"},
      body:body.toString()
    });
    const session=await response.json();
    if(!response.ok || typeof session.url!=="string" || !session.url.startsWith("https://checkout.stripe.com/"))
      return respond({error:"Secure checkout is temporarily unavailable."},502);
    return respond({url:session.url});
  } catch {return respond({error:"Secure checkout is temporarily unavailable."},502);}
}
