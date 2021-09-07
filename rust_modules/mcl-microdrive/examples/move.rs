use clap::{Arg, App};

fn main() {
    let matches = App::new("CLI interface for moving the first MCL microstage found")
        .version("0.1.0")
        .author("Hayley Deckers <h.deckers@students.uu.nl>")
        // .about("")
        .arg(Arg::with_name("no_wait")
                //  .short("f")
                 .long("no-wait")
                 .takes_value(false)
                 .help("Should the program wait for the move to complete?"))
        .arg(Arg::with_name("M1")
                 .short("x")
                 .long("M1")
                 .takes_value(true)
                 .help("how much and how fast to move along the first axis in mm and mm/s {distance,speed}"))
        .arg(Arg::with_name("M2")
                 .short("y")
                 .long("M2")
                 .takes_value(true)
                 .help("how much and how fast to move along the second axis in mm and mm/s {distance,speed}"))
        .arg(Arg::with_name("M3")
                 .short("z")
                 .long("M3")
                 .takes_value(true)
                 .help("how much and how fast to move along the third axis in mm and mm/s {distance,speed}"))
        .get_matches();

    let x_arg = matches.value_of("M1");
    let y_arg = matches.value_of("M2");
    let z_arg = matches.value_of("M3");
    if x_arg.is_none() && y_arg.is_none() && z_arg.is_none() {
        eprintln!("Specify at least one axis to move on!");
        std::process::exit(-1);
    }
    let dev = &mcl_microdrive::get_all_devices()[0];
    let axis_info = dev.axis_info().unwrap();
    if x_arg.is_some() && !axis_info.axis_M1_is_available() {
        eprintln!("This device does not support moving on the x-axis");
        std::process::exit(-1);
    }
    if y_arg.is_some() && !axis_info.axis_M2_is_available() {
        eprintln!("This device does not support moving on the y-axis");
        std::process::exit(-1);
    }
    if z_arg.is_some() && !axis_info.axis_M3_is_available() {
        eprintln!("This device does not support moving on the z-axis");
        std::process::exit(-1);
    }
    
    fn str_to_tuple(input : &str) -> (f64, f64) {
        let mut split = input.split(',');
        (split.next().expect("Expected a value after axis argument").parse::<f64>().expect("failed to parse number"), split.next().expect("Expected a speed directly after distance argument (don't put a space after \",\")").parse::<f64>().expect("failed to parse number"))
    }
    let x_val = x_arg.map(|s| str_to_tuple(s)).unwrap_or((0.0,0.0));
    let y_val = y_arg.map(|s| str_to_tuple(s)).unwrap_or((0.0,0.0));
    let z_val = z_arg.map(|s| str_to_tuple(s)).unwrap_or((0.0,0.0));
    let x_axis = if x_arg.is_some() { mcl_microdrive::Axis::M1 } else { mcl_microdrive::Axis::NoAxis };
    let y_axis = if y_arg.is_some() { mcl_microdrive::Axis::M2 } else { mcl_microdrive::Axis::NoAxis };
    let z_axis = if z_arg.is_some() { mcl_microdrive::Axis::M3 } else { mcl_microdrive::Axis::NoAxis };

    println!("isueing move of {:?} {:?}, {:?} {:?}, {:?} {:?})", x_axis, x_val, y_axis, y_val, z_axis, z_val);
}