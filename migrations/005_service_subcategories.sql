-- ============================================================ 005 — Service sub-categories
-- Each service page lists its sub-categories (cards with optional image).
-- Additive only; existing rows get an empty list.

ALTER TABLE services ADD COLUMN IF NOT EXISTS subcategories JSONB NOT NULL DEFAULT '[]';

UPDATE services SET subcategories = '[
 {"title":"Below-Knee (BK) Prosthetic Leg","icon":"🦵","desc":"For partial-foot to below-knee amputations. Lightweight socket with natural, energy-efficient walking.","img":""},
 {"title":"Above-Knee (AK) Prosthetic Leg","icon":"🦿","desc":"Complete above-knee solutions with mechanical or hydraulic knee joints, matched to your activity level.","img":"/static/img/gallery/ak-prosthesis.jpg"},
 {"title":"Microprocessor Knee Systems","icon":"🧠","desc":"Computer-controlled knees that adapt every step for smooth, safe walking on stairs and slopes.","img":"/static/img/gallery/microprocessor-knee.jpg"},
 {"title":"Carbon Energy-Storing Feet","icon":"⚡","desc":"Springy carbon feet that return energy with every step - for active users and sports.","img":"/static/img/gallery/carbon-feet.jpg"},
 {"title":"Hip Disarticulation Prosthetics","icon":"🩺","desc":"Specialised sockets and suspension for high-level amputations, fitted with extra care and time."},
 {"title":"Silicone Cosmetic Covering","icon":"✨","desc":"Lifelike silicone covers matched to your skin tone so the prosthesis looks natural."}
]' WHERE slug = 'lower-limb-prosthetics';

UPDATE services SET subcategories = '[
 {"title":"Myoelectric / Bionic Hand","icon":"🤖","desc":"Sensor-controlled hands with natural grip patterns, charged by battery - no body straps needed.","img":"/static/img/gallery/bionic-hand.jpg"},
 {"title":"Body-Powered Arm Systems","icon":"🔗","desc":"Durable, reliable harness-operated hooks and hands - a favourite for heavy daily work."},
 {"title":"Cosmetic Passive Hand","icon":"🖐️","desc":"Lightweight realistic hand for appearance and light support, custom-matched to your skin."},
 {"title":"Below-Elbow Prosthetics","icon":"💪","desc":"Wrist-level and below-elbow solutions keeping maximum natural movement."},
 {"title":"Above-Elbow Prosthetics","icon":"🦾","desc":"Full arm replacement with elbow joint options - mechanical or electronic."},
 {"title":"Silicone Fingers & Partial Hands","icon":"✋","desc":"Ultra-realistic silicone fingers and partial-hand restorations.","img":"/static/img/gallery/silicone-hand.jpg"}
]' WHERE slug = 'upper-limb-prosthetics';

UPDATE services SET subcategories = '[
 {"title":"AFO - Foot Drop Brace","icon":"🦶","desc":"Lightweight braces that lift the foot during walking after stroke, nerve injury or polio.","img":"/static/img/gallery/afo-brace.jpg"},
 {"title":"KAFO Calipers","icon":"🩼","desc":"Knee-ankle-foot support for weak or paralysed legs, with walking-joint options.","img":"/static/img/gallery/kafo-brace.jpg"},
 {"title":"Knee Braces (OA & Ligament)","icon":"🧎","desc":"Support for knee pain, arthritis and ligament injuries - offloading and stabilising."},
 {"title":"Spine & Posture Braces","icon":"🧍","desc":"TLSO and lumbar supports for scoliosis, fractures and back-pain relief."},
 {"title":"Wrist, Hand & Finger Splints","icon":"🖐️","desc":"Custom splints for fractures, tendon injuries and post-surgery recovery."}
]' WHERE slug = 'orthotics-braces';

UPDATE services SET subcategories = '[
 {"title":"Diabetic Footwear","icon":"👞","desc":"Extra-depth pressure-relief shoes that protect sensitive feet and prevent ulcers.","img":"/static/img/gallery/diabetic-footwear.jpg"},
 {"title":"Custom MCR Insoles","icon":"🧩","desc":"Soft cushioning insoles moulded to your feet to spread pressure evenly."},
 {"title":"Ulcer-Prevention Shoes","icon":"🛡️","desc":"Specialised chappals and shoes for healed or high-risk ulcer feet."},
 {"title":"Silicone Toe Protectors","icon":"🦶","desc":"Soft silicone caps and separators that shield toes from friction and pressure."}
]' WHERE slug = 'diabetic-foot-care';

UPDATE services SET subcategories = '[
 {"title":"Pediatric Prosthetic Limbs","icon":"🧒","desc":"Growing-child limbs designed light and strong, resized as your child grows."},
 {"title":"Clubfoot Braces (Denis Browne)","icon":"👶","desc":"Corrective boots-and-bar systems for clubfoot correction at home."},
 {"title":"Childrens AFOs & Calipers","icon":"🦵","desc":"Colourful, child-friendly braces for polio, CP and developmental needs."},
 {"title":"Growth Adjustment Follow-ups","icon":"📏","desc":"Regular socket and brace adjustments scheduled as children grow."}
]' WHERE slug = 'pediatric-care';

UPDATE services SET subcategories = '[
 {"title":"Gait Training with New Prosthesis","icon":"🚶","desc":"Step-by-step walking training until you walk confidently, indoors and outdoors."},
 {"title":"Balance & Strengthening","icon":"⚖️","desc":"Core and leg exercises that make prosthetic walking safe and steady."},
 {"title":"Stump Care & Desensitisation","icon":"🧴","desc":"Skin care, shaping and volume management for a comfortable socket fit."},
 {"title":"Stairs, Slopes & Outdoor Training","icon":"🏞️","desc":"Advanced training for real life - stairs, ramps, uneven ground and crowds."}
]' WHERE slug = 'rehabilitation-gait-training';

UPDATE services SET subcategories = '[
 {"title":"Prosthesis Repair (Any Brand)","icon":"🔧","desc":"Quick repairs for limbs bought anywhere - straps, joints, feet and alignment."},
 {"title":"Socket Re-Fit & Adjustment","icon":"🧰","desc":"Socket reshaping or replacement when your limb volume changes."},
 {"title":"Parts Replacement","icon":"⚙️","desc":"Feet, knees, tubes, adapters and straps replaced with genuine parts."},
 {"title":"Preventive Maintenance Check","icon":"🛠️","desc":"Yearly safety inspection so small problems never become big ones."}
]' WHERE slug = 'repair-maintenance';

UPDATE services SET subcategories = '[
 {"title":"Home Measurement & Casting","icon":"📐","desc":"We visit your home for casting and measurement when travel is difficult."},
 {"title":"Home Fitting & Delivery","icon":"🏠","desc":"Final fitting and handover done at your doorstep with full explanation."},
 {"title":"Follow-up Home Visits","icon":"🔄","desc":"Comfort checks and small adjustments at home after delivery."},
 {"title":"Care for Elderly & Bedridden Patients","icon":"❤️","desc":"Gentle, unhurried care planned around the routine and comfort of the patient."}
]' WHERE slug = 'home-visit-service';
